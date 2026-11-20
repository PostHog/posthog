import { ChildProcess, execFileSync, spawn } from 'child_process'
import {
    appendFileSync,
    existsSync,
    mkdirSync,
    mkdtempSync,
    readFileSync,
    readdirSync,
    rmSync,
    statSync,
    writeFileSync,
} from 'fs'
import os from 'os'
import path from 'path'

import { parseJSON } from '~/common/utils/json-parse'

const WRAPPER = path.join(__dirname, 'host-run-card.sh')
const RUN_ID = '00000000-0000-4000-8000-000000000001'
const EARLIER_RUN_ID = '00000000-0000-4000-8000-000000000002'
const BUCKET = 'test-evidence'
const START = '{"type":"start","at":1}'
const TICK = '{"type":"tick","at":2}'
const END = '{"type":"end","at":3}'

const FAKE_AWS = `#!/usr/bin/env bash
[ "$1 $2" = "s3 cp" ] || exit 2
shift 2
recursive=false
paths=()
for arg in "$@"; do
    case $arg in
    --recursive) recursive=true ;;
    --only-show-errors) ;;
    *) paths+=("$arg") ;;
    esac
done
target="$FAKE_S3/\${paths[1]#s3://}"
mkdir -p "$(dirname "$target")"
if $recursive; then
    mkdir -p "$target"
    cp -r "\${paths[0]}"/. "$target"/
    exit
fi
case $target in
*/live.jsonl)
    [ -z "\${FAKE_LIVE_FAILS:-}" ] || exit 1
    [ -z "\${FAKE_LIVE_DELAY:-}" ] || sleep "$FAKE_LIVE_DELAY"
    if [ "\${FAKE_LIVE_HANGS:-}" = every ] || { [ "\${FAKE_LIVE_HANGS:-}" = first ] && [ -z "$(ls "$FAKE_S3.held" 2>/dev/null)" ]; }; then
        trap '' TERM
        mkdir -p "$FAKE_S3.held"
        cat >"$FAKE_S3.held/.part" && mv "$FAKE_S3.held/.part" "$FAKE_S3.held/$(ls "$FAKE_S3.held" | wc -l)"
        exec sleep 1000
    fi
    ;;
esac
cat >"$target.part" && mv "$target.part" "$target"
`

const FAKE_RUNNER = `#!/usr/bin/env bash
echo $$ >"$FAKE_RUNNER_PID"
run="$XDG_CACHE_HOME/posthog-scenarios/${RUN_ID}"
mkdir -p "$run"
end_live_log() { [ -z "\${FAKE_LIVE:-}" ] || printf '%s\\n%s\\n' '${TICK.slice(14)}' '${END}' >>"$run/live.jsonl"; }
[ -z "\${FAKE_SLOW_STOP:-}" ] || trap 'sleep "$FAKE_SLOW_STOP"; end_live_log; exit 0' TERM
[ -z "\${FAKE_STUCK_STOP:-}" ] || trap 'end_live_log; sleep 1000' TERM
[ -z "\${FAKE_LIVE:-}" ] || printf '%s\\n%s' '${START}' '${TICK.slice(0, 14)}' >>"$run/live.jsonl"
[ -z "\${FAKE_CARD_SECONDS:-}" ] || sleep "$FAKE_CARD_SECONDS"
if [ -n "\${FAKE_HOLD:-}" ]; then
    while [ ! -e "$FAKE_RELEASE" ]; do sleep 0.02; done
fi
end_live_log
exit "\${FAKE_CARD_EXIT:-0}"
`

type Run = { dir: string; wrapper: ChildProcess; exited: Promise<number | null> }
type LiveLogOnHost = { runId: string; content: string }

const liveLogIn = (dir: string, runId: string): string =>
    path.join(dir, 'host', 'cache', 'posthog-scenarios', runId, 'live.jsonl')

describe('host-live-copy.sh, run by host-run-card.sh', () => {
    let root: string
    const runs: Run[] = []

    function start(name: string, env: NodeJS.ProcessEnv, onHost?: LiveLogOnHost): Run {
        const dir = path.join(root, name)
        const bin = path.join(dir, 'bin')
        const host = path.join(dir, 'host')
        mkdirSync(bin, { recursive: true })
        mkdirSync(path.join(host, 'input'), { recursive: true })
        mkdirSync(path.join(host, 'pooler'), { recursive: true })
        writeFileSync(path.join(host, 'input', 'manifest.json'), JSON.stringify({ runId: RUN_ID, card: 'any-card' }))
        writeFileSync(path.join(host, 'pooler', 'urls'), 'postgres://127.0.0.1:6432/cyclotron_node\n')
        writeFileSync(path.join(bin, 'aws'), FAKE_AWS, { mode: 0o755 })
        writeFileSync(path.join(bin, 'node'), FAKE_RUNNER, { mode: 0o755 })
        if (onHost) {
            const liveLog = liveLogIn(dir, onHost.runId)
            mkdirSync(path.dirname(liveLog), { recursive: true })
            writeFileSync(liveLog, onHost.content)
        }
        const wrapper = spawn('bash', [WRAPPER], {
            cwd: dir,
            env: {
                ...process.env,
                PATH: `${bin}:${process.env.PATH}`,
                HOME: dir,
                SCENARIO_RUN_ID: RUN_ID,
                SCENARIO_EVIDENCE_BUCKET: BUCKET,
                SCENARIO_HOST_ROOT: host,
                SCENARIO_PROCESS_LOGS: path.join(dir, 'processes'),
                SCENARIO_LIVE_COPY_SECONDS: '0.2',
                TMPDIR: dir,
                FAKE_S3: path.join(dir, 's3'),
                FAKE_RELEASE: path.join(dir, 'release'),
                FAKE_RUNNER_PID: path.join(dir, 'runner.pid'),
                ...env,
            },
            stdio: 'ignore',
            detached: true,
        })
        const exited = new Promise<number | null>((resolve) => wrapper.once('exit', (code) => resolve(code)))
        const run = { dir, wrapper, exited }
        runs.push(run)
        return run
    }

    const object = (run: Run, key: string): string => path.join(run.dir, 's3', BUCKET, 'runs', RUN_ID, key)
    const release = (run: Run): void => writeFileSync(path.join(run.dir, 'release'), '')
    const signalAll = (run: Run, signal: NodeJS.Signals): void => {
        try {
            process.kill(-run.wrapper.pid!, signal)
        } catch {}
    }

    async function until(check: () => boolean, what: string): Promise<void> {
        for (const deadline = Date.now() + 10_000; !check(); ) {
            if (Date.now() > deadline) {
                throw new Error(`Still waiting for ${what}`)
            }
            await new Promise((resolve) => setTimeout(resolve, 20))
        }
    }

    const held = (run: Run): string[] => {
        const dir = path.join(run.dir, 's3.held')
        return existsSync(dir)
            ? readdirSync(dir)
                  .filter((name) => /^\d+$/.test(name))
                  .sort((a, b) => Number(a) - Number(b))
                  .map((name) => readFileSync(path.join(dir, name), 'utf8'))
            : []
    }

    const copied = (run: Run): string =>
        existsSync(object(run, 'live.jsonl')) ? readFileSync(object(run, 'live.jsonl'), 'utf8') : ''

    function processesOf(run: Run): string[][] {
        return execFileSync('ps', ['-eo', 'pid=,ppid=,sid=,stat=,args='], { encoding: 'utf8' })
            .split('\n')
            .map((line) => line.trim().split(/\s+/))
            .filter(([, , sid, stat]) => sid === String(run.wrapper.pid) && !stat?.startsWith('Z'))
    }

    function processesBesideTheRunner(run: Run): string[][] {
        const runner = readFileSync(path.join(run.dir, 'runner.pid'), 'utf8').trim()
        return processesOf(run).filter(([pid, ppid]) => pid !== runner && ppid !== runner)
    }

    function evidenceOf(run: Run): string[] {
        const list = (dir: string): string[] =>
            readdirSync(dir, { withFileTypes: true }).flatMap((entry) =>
                entry.isDirectory()
                    ? list(path.join(dir, entry.name)).map((child) => `${entry.name}/${child}`)
                    : [entry.name]
            )
        return list(object(run, 'evidence')).sort()
    }

    async function outcomeOf(run: Run): Promise<object> {
        const exitCode = await run.exited
        const { at: _, ...done } = parseJSON(readFileSync(object(run, 'host/done'), 'utf8')) as { at: string }
        return { exitCode, done, evidence: evidenceOf(run) }
    }

    beforeEach(() => {
        root = mkdtempSync(path.join(os.tmpdir(), 'scenario-live-copy-'))
    })

    afterEach(() => {
        for (const run of runs.splice(0)) {
            signalAll(run, 'SIGKILL')
        }
        rmSync(root, { recursive: true, force: true })
    })

    it.each([
        ['', {}],
        [', even when one copy takes longer than the interval', { FAKE_LIVE_DELAY: '0.5' }],
    ])(
        'copies each whole line of the live log to the run while the card runs, and the rest when it ends%s',
        async (_, env) => {
            const run = start(
                'run',
                { ...env, FAKE_HOLD: '1' },
                { runId: RUN_ID, content: `${START}\n${TICK.slice(0, 14)}` }
            )
            const liveLog = liveLogIn(run.dir, RUN_ID)

            await until(() => copied(run) === `${START}\n`, 'the first whole line')
            appendFileSync(liveLog, `${TICK.slice(14)}\n`)
            await until(() => copied(run) === `${START}\n${TICK}\n`, 'the next whole line')
            appendFileSync(liveLog, `${END}\n`)
            release(run)
            await run.exited

            expect(copied(run)).toBe(`${START}\n${TICK}\n${END}\n`)
        }
    )

    it('makes a final copy when the card ends between two copies', async () => {
        const run = start('run', { FAKE_LIVE: '1', FAKE_HOLD: '1', SCENARIO_LIVE_COPY_SECONDS: '600' })

        await until(() => existsSync(liveLogIn(run.dir, RUN_ID)), 'the live log')
        release(run)
        await run.exited

        expect(readFileSync(object(run, 'live.jsonl'), 'utf8')).toBe(readFileSync(liveLogIn(run.dir, RUN_ID), 'utf8'))
    })

    it('copies the records the card writes as it stops when the whole run is stopped at once', async () => {
        const run = start('run', { FAKE_LIVE: '1', FAKE_HOLD: '1', FAKE_SLOW_STOP: '0.5' })
        await until(() => existsSync(object(run, 'live.jsonl')), 'a live log copy')

        signalAll(run, 'SIGTERM')
        await run.exited

        expect(readFileSync(object(run, 'live.jsonl'), 'utf8')).toBe(`${START}\n${TICK}\n${END}\n`)
    })

    it.each([
        ['every live log copy fails', { FAKE_LIVE: '1', FAKE_LIVE_FAILS: '1', FAKE_CARD_SECONDS: '1' }],
        ['the card ends before the first copy', { FAKE_LIVE: '1' }],
        ['the card writes no live log', {}],
    ])('ends the run as it would without live copy when %s', async (_, env) => {
        for (const cardExit of ['0', '1']) {
            const without = start(`without-${cardExit}`, {
                ...env,
                FAKE_CARD_EXIT: cardExit,
                SCENARIO_LIVE_COPY: 'off',
            })
            const withCopy = start(`with-${cardExit}`, { ...env, FAKE_CARD_EXIT: cardExit })

            expect(await outcomeOf(withCopy)).toEqual(await outcomeOf(without))
        }
    })

    it('copies nothing when live copy is off', async () => {
        const run = start('run', { FAKE_LIVE: '1', SCENARIO_LIVE_COPY: 'off' })

        await run.exited

        expect(parseJSON(readFileSync(object(run, 'host/done'), 'utf8'))).toMatchObject({ exitCode: 0, uploaded: true })
        expect(existsSync(object(run, 'live.jsonl'))).toBe(false)
    })

    it.each([
        [
            'cancels a copy in flight and makes its final copy',
            'first',
            '60',
            [`${START}\n`],
            `${START}\n${TICK}\n${END}\n`,
        ],
        ['bounds a final copy that hangs', 'every', '1', [`${START}\n`, `${START}\n${TICK}\n${END}\n`], undefined],
    ])('%s when the card ends', async (_, hangs, limit, heldUploads, finalCopy) => {
        const run = start('run', {
            FAKE_LIVE: '1',
            FAKE_HOLD: '1',
            FAKE_LIVE_HANGS: hangs,
            SCENARIO_LIVE_COPY_SECONDS: '600',
            SCENARIO_LIVE_COPY_LIMIT_SECONDS: limit,
        })

        await until(() => held(run).length > 0, 'a hanging copy')
        release(run)
        const ended = await Promise.race([
            run.exited.then(() => true),
            new Promise<false>((resolve) => setTimeout(() => resolve(false), 15_000)),
        ])

        expect(ended).toBe(true)
        expect(parseJSON(readFileSync(object(run, 'host/done'), 'utf8'))).toMatchObject({ exitCode: 0, uploaded: true })
        expect(held(run)).toEqual(heldUploads)
        expect(existsSync(object(run, 'live.jsonl')) ? copied(run) : undefined).toBe(finalCopy)
    })

    it('marks the run done while a final copy hangs, and waits for that copy before it exits', async () => {
        const run = start('run', {
            FAKE_LIVE: '1',
            FAKE_HOLD: '1',
            FAKE_CARD_EXIT: '1',
            FAKE_LIVE_HANGS: 'every',
            SCENARIO_LIVE_COPY_SECONDS: '600',
            SCENARIO_LIVE_COPY_LIMIT_SECONDS: '60',
        })
        await until(() => held(run).length > 0, 'a hanging copy')

        release(run)
        await until(() => held(run).includes(`${START}\n${TICK}\n${END}\n`), 'the final copy to hang')
        await until(() => existsSync(object(run, 'host/done')), 'the run to be marked done')

        expect(parseJSON(readFileSync(object(run, 'host/done'), 'utf8'))).toMatchObject({ exitCode: 1, uploaded: true })
        expect(run.wrapper.exitCode).toBeNull()
    })

    it('leaves no process behind when the whole run is killed during a copy', async () => {
        const run = start('run', { FAKE_HOLD: '1', FAKE_LIVE_HANGS: 'first' }, { runId: RUN_ID, content: `${START}\n` })
        await until(() => held(run).length > 0, 'a hanging copy')

        signalAll(run, 'SIGKILL')

        await until(() => processesOf(run).length === 0, 'every process of the run to end')
    })

    it('leaves no process but the card behind once the wrapper is gone during a copy', async () => {
        const run = start(
            'run',
            {
                FAKE_HOLD: '1',
                FAKE_LIVE_HANGS: 'first',
                SCENARIO_LIVE_COPY_SECONDS: '600',
                SCENARIO_LIVE_COPY_LIMIT_SECONDS: '60',
            },
            { runId: RUN_ID, content: `${START}\n` }
        )
        await until(() => held(run).length > 0, 'a hanging copy')

        run.wrapper.kill('SIGKILL')

        await until(() => processesBesideTheRunner(run).length === 0, 'the copy loop and its upload to end')
    })

    it.each([
        ['', {}, false],
        [' while it stops', { FAKE_STUCK_STOP: '1' }, true],
    ])(
        'leaves no process but the card behind, and copies nothing more, once the wrapper is gone%s',
        async (_, env, stopping) => {
            const run = start(
                'run',
                { ...env, FAKE_LIVE: '1', FAKE_HOLD: '1', SCENARIO_LIVE_COPY_SECONDS: '600' },
                { runId: RUN_ID, content: `${START}\n` }
            )
            await until(
                () =>
                    existsSync(object(run, 'live.jsonl')) &&
                    Date.now() - statSync(object(run, 'live.jsonl')).mtimeMs > 1000,
                'the copy loop to wait a second past its first copy'
            )
            const before = copied(run)

            if (stopping) {
                signalAll(run, 'SIGTERM')
                await until(
                    () => readFileSync(liveLogIn(run.dir, RUN_ID), 'utf8').endsWith(`${END}\n`),
                    'the card to write its last records'
                )
            }
            run.wrapper.kill('SIGKILL')

            await until(() => processesBesideTheRunner(run).length === 0, 'the copy loop to end')
            expect(copied(run)).toBe(before)
        }
    )

    it('never copies the live log of an earlier run on the same host', async () => {
        const run = start(
            'run',
            {},
            {
                runId: EARLIER_RUN_ID,
                content: `${START}\n${END}\n`,
            }
        )

        await run.exited

        expect(existsSync(object(run, 'host/done'))).toBe(true)
        expect(existsSync(object(run, 'live.jsonl'))).toBe(false)
    })
})
