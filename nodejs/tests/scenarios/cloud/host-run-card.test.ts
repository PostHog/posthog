import { ChildProcess, execFileSync, spawn } from 'child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs'
import os from 'os'
import path from 'path'

import { parseJSON } from '~/common/utils/json-parse'

const WRAPPER = path.join(__dirname, 'host-run-card.sh')
const RUN_ID = '00000000-0000-4000-8000-000000000001'
const RUNNER_RUN_ID = '00000000-0000-4000-8000-000000000002'
const BUCKET = 'test-evidence'
const POOLER_URLS =
    'postgres://scn%20admin:p%40ss@127.0.0.1:6432/cyclotron_node,postgres://scn%20admin:p%40ss@127.0.0.1:6433/cyclotron_node'

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
if $recursive; then
    [ -z "\${FAKE_UPLOAD_FAILS:-}" ] || exit 1
    mkdir -p "$target"
    cp -r "\${paths[0]}"/. "$target"/
else
    case $target in */host/"\${FAKE_MARK_FAILS:-}") exit 1 ;; esac
    mkdir -p "$(dirname "$target")"
    cat >"$target"
fi
`

const FAKE_RUNNER = `#!/usr/bin/env bash
state="$XDG_CACHE_HOME/posthog-scenarios"
run="$state/${RUNNER_RUN_ID}"
mkdir -p "$run" "$state/edge-ca"
printf '%s' "$SCENARIO_POOLER_URLS" >"$state/pooler-urls"
echo '{"phase":"drive"}' >"$run/result.json"
echo 'hogli up exited 1' >"$state/hogli.log"
echo 'private key' >"$state/edge-ca/ca.key"
[ -z "\${FAKE_CARD_BLOCKS_COPY:-}" ] || touch "$SCENARIO_HOST_ROOT/evidence/run"
if [ -n "\${FAKE_CARD_HANGS:-}" ]; then
    trap 'sleep 0.5; echo interrupted >"$run/interrupted"; exit 2' TERM
    touch "$run/running"
    while :; do sleep 0.1; done
fi
exit "\${FAKE_CARD_EXIT:-0}"
`

const FAKE_PNPM = `#!/usr/bin/env bash
node "$@" &
child=$!
trap 'kill -TERM "$child"; exit 143' TERM
wait "$child"
`

describe('host-run-card.sh', () => {
    let dir: string

    const s3 = (key: string): string => path.join(dir, 's3', BUCKET, 'runs', RUN_ID, key)

    function start(
        env: NodeJS.ProcessEnv,
        manifest: object = { card: 'cyclotron-scale' },
        runner = FAKE_RUNNER,
        poolerUrls: string | null = POOLER_URLS
    ): ChildProcess {
        const bin = path.join(dir, 'bin')
        mkdirSync(bin)
        mkdirSync(path.join(dir, 'host', 'input'), { recursive: true })
        writeFileSync(path.join(dir, 'host', 'input', 'manifest.json'), JSON.stringify({ runId: RUN_ID, ...manifest }))
        if (poolerUrls !== null) {
            mkdirSync(path.join(dir, 'host', 'pooler'), { recursive: true })
            writeFileSync(path.join(dir, 'host', 'pooler', 'urls'), `${poolerUrls}\n`)
        }
        writeFileSync(path.join(bin, 'aws'), FAKE_AWS, { mode: 0o755 })
        if (runner) {
            writeFileSync(path.join(bin, 'node'), runner, { mode: 0o755 })
        }
        writeFileSync(path.join(bin, 'pnpm'), FAKE_PNPM, { mode: 0o755 })
        return spawn('bash', [WRAPPER], {
            env: {
                ...process.env,
                PATH: `${bin}:${process.env.PATH}`,
                HOME: dir,
                SCENARIO_RUN_ID: RUN_ID,
                SCENARIO_EVIDENCE_BUCKET: BUCKET,
                SCENARIO_HOST_ROOT: path.join(dir, 'host'),
                FAKE_S3: path.join(dir, 's3'),
                ...env,
            },
            stdio: 'ignore',
        })
    }

    const exited = (child: ChildProcess): Promise<number | null> =>
        new Promise((resolve) => child.once('exit', (code) => resolve(code)))

    async function whenExists(file: string): Promise<void> {
        while (!existsSync(file)) {
            await new Promise((resolve) => setTimeout(resolve, 10))
        }
    }

    beforeEach(() => {
        dir = mkdtempSync(path.join(os.tmpdir(), 'scenario-host-'))
    })

    afterEach(() => rmSync(dir, { recursive: true, force: true }))

    it.each([
        ['the card passes', { FAKE_CARD_EXIT: '0' }, 0, true],
        ['the card fails', { FAKE_CARD_EXIT: '1' }, 1, true],
        ['the evidence upload fails', { FAKE_CARD_EXIT: '1', FAKE_UPLOAD_FAILS: '1' }, 1, false],
        ['the evidence cannot be copied', { FAKE_CARD_EXIT: '0', FAKE_CARD_BLOCKS_COPY: '1' }, 0, false],
    ])('marks done with the runner exit code when %s', async (_, env, exitCode, uploaded) => {
        await exited(start(env))

        expect(existsSync(s3('host/started'))).toBe(true)
        expect(parseJSON(readFileSync(s3('host/done'), 'utf8'))).toMatchObject({ exitCode, uploaded })
        expect(existsSync(s3(`evidence/run/${RUNNER_RUN_ID}/result.json`))).toBe(uploaded)
        expect(existsSync(s3('evidence/hogli.log')) && readFileSync(s3('evidence/hogli.log'), 'utf8')).toBe(
            uploaded && 'hogli up exited 1\n'
        )
        expect(existsSync(s3('evidence/run/edge-ca'))).toBe(false)
    })

    it('runs the card the run manifest names', async () => {
        await exited(start({}, { card: 'cyclotron-scale' }, ''))

        expect(parseJSON(readFileSync(s3('host/done'), 'utf8'))).toMatchObject({ exitCode: 2, uploaded: true })
        expect(readFileSync(s3('evidence/card.log'), 'utf8')).toContain(
            'cards/cyclotron-scale.yaml is not a valid card'
        )
    })

    it('hands the runner the URLs of the poolers in front of the run cluster', async () => {
        await exited(start({}))

        expect(readFileSync(path.join(dir, 'host', 'cache', 'posthog-scenarios', 'pooler-urls'), 'utf8')).toBe(
            POOLER_URLS
        )
    })

    it.each<[string, NodeJS.ProcessEnv, object, string | null]>([
        ['it cannot mark it started', { FAKE_MARK_FAILS: 'started' }, { card: 'cyclotron-scale' }, POOLER_URLS],
        ['the run manifest names no card', {}, {}, POOLER_URLS],
        [
            'the run manifest names a file in place of a card',
            {},
            { card: '/opt/scenario/input/other.yaml' },
            POOLER_URLS,
        ],
        ['the host started no pooler', {}, { card: 'cyclotron-scale' }, null],
    ])('never starts the card when %s', async (_story, env, manifest, poolerUrls) => {
        await exited(start(env, manifest, FAKE_RUNNER, poolerUrls))

        expect(parseJSON(readFileSync(s3('host/done'), 'utf8'))).toMatchObject({ exitCode: 2 })
        expect(existsSync(path.join(dir, 'host', 'cache', 'posthog-scenarios'))).toBe(false)
    })

    it('stops the card on SIGTERM and uploads its evidence once the runner finished its cleanup', async () => {
        const wrapper = start({ FAKE_CARD_HANGS: '1' })
        const done = exited(wrapper)
        await whenExists(path.join(dir, 'host', 'cache', 'posthog-scenarios', RUNNER_RUN_ID, 'running'))

        wrapper.kill('SIGTERM')
        await done

        expect(parseJSON(readFileSync(s3('host/done'), 'utf8'))).toMatchObject({ exitCode: 2, uploaded: true })
        expect(readFileSync(s3(`evidence/run/${RUNNER_RUN_ID}/interrupted`), 'utf8')).toBe('interrupted\n')
        expect(() =>
            execFileSync('sha256sum', ['--check', '--strict', 'SHA256SUMS'], { cwd: s3('evidence') })
        ).not.toThrow()
    })
})
