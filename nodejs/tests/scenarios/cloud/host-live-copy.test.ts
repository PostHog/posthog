import { ChildProcess, execFileSync, spawn } from 'child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'fs'
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
    if [ -n "\${FAKE_LIVE_HANGS:-}" ]; then
        touch "$FAKE_S3.hanging"
        exec sleep 1000
    fi
    ;;
esac
cat >"$target.part" && mv "$target.part" "$target"
`

const FAKE_RUNNER = `#!/usr/bin/env bash
run="$XDG_CACHE_HOME/posthog-scenarios/${RUN_ID}"
mkdir -p "$run"
[ -z "\${FAKE_LIVE:-}" ] || printf '%s\\n%s' '${START}' '${TICK.slice(0, 14)}' >>"$run/live.jsonl"
[ -z "\${FAKE_CARD_SECONDS:-}" ] || sleep "$FAKE_CARD_SECONDS"
if [ -n "\${FAKE_HOLD:-}" ]; then
    while [ ! -e "$FAKE_RELEASE" ]; do sleep 0.02; done
fi
[ -z "\${FAKE_LIVE:-}" ] || printf '%s\\n%s\\n' '${TICK.slice(14)}' '${END}' >>"$run/live.jsonl"
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
                FAKE_S3: path.join(dir, 's3'),
                FAKE_RELEASE: path.join(dir, 'release'),
                ...env,
            },
            stdio: 'ignore',
        })
        const exited = new Promise<number | null>((resolve) => wrapper.once('exit', (code) => resolve(code)))
        const run = { dir, wrapper, exited }
        runs.push(run)
        return run
    }

    const object = (run: Run, key: string): string => path.join(run.dir, 's3', BUCKET, 'runs', RUN_ID, key)
    const release = (run: Run): void => writeFileSync(path.join(run.dir, 'release'), '')

    async function until(check: () => boolean, what: string): Promise<void> {
        for (const deadline = Date.now() + 10_000; !check(); ) {
            if (Date.now() > deadline) {
                throw new Error(`Still waiting for ${what}`)
            }
            await new Promise((resolve) => setTimeout(resolve, 20))
        }
    }

    function copyLoopsOf(run: Run): string[] {
        return execFileSync('ps', ['-eo', 'args'], { encoding: 'utf8' })
            .split('\n')
            .filter((args) => args.includes('host-live-copy.sh') && args.includes(run.dir))
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
            release(run)
            run.wrapper.kill('SIGKILL')
        }
        rmSync(root, { recursive: true, force: true })
    })

    it('copies the whole lines of the live log to the run while the card runs, and the rest when it ends', async () => {
        const run = start('run', { FAKE_LIVE: '1', FAKE_HOLD: '1' })

        await until(() => existsSync(object(run, 'live.jsonl')), 'a live log copy')
        expect(readFileSync(object(run, 'live.jsonl'), 'utf8')).toBe(`${START}\n`)

        release(run)
        await run.exited
        expect(readFileSync(object(run, 'live.jsonl'), 'utf8')).toBe(`${START}\n${TICK}\n${END}\n`)
    })

    it('makes a final copy when the card ends between two copies', async () => {
        const run = start('run', { FAKE_LIVE: '1', FAKE_HOLD: '1', SCENARIO_LIVE_COPY_SECONDS: '600' })

        await until(() => existsSync(liveLogIn(run.dir, RUN_ID)), 'the live log')
        release(run)
        await run.exited

        expect(readFileSync(object(run, 'live.jsonl'), 'utf8')).toBe(readFileSync(liveLogIn(run.dir, RUN_ID), 'utf8'))
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

        expect(existsSync(object(run, 'host/done'))).toBe(true)
        expect(existsSync(object(run, 'live.jsonl'))).toBe(false)
    })

    it('stops at once with a copy in flight, and bounds its final copy', async () => {
        const run = start(
            'run',
            {
                FAKE_HOLD: '1',
                FAKE_LIVE_HANGS: '1',
                SCENARIO_LIVE_COPY_SECONDS: '600',
                SCENARIO_LIVE_COPY_FINAL_SECONDS: '1',
            },
            { runId: RUN_ID, content: `${START}\n` }
        )

        await until(() => existsSync(path.join(run.dir, 's3.hanging')), 'a hanging copy')
        release(run)
        const ended = await Promise.race([
            run.exited.then(() => true),
            new Promise<false>((resolve) => setTimeout(() => resolve(false), 15_000)),
        ])

        expect(ended).toBe(true)
        expect(parseJSON(readFileSync(object(run, 'host/done'), 'utf8'))).toMatchObject({ exitCode: 0, uploaded: true })
    })

    it('ends on its own when the wrapper is gone', async () => {
        const run = start('run', { FAKE_LIVE: '1', FAKE_HOLD: '1' })
        await until(() => existsSync(object(run, 'live.jsonl')), 'a live log copy')
        expect(copyLoopsOf(run)).toHaveLength(1)

        run.wrapper.kill('SIGKILL')

        await until(() => copyLoopsOf(run).length === 0, 'the copy loop to end')
    })

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
