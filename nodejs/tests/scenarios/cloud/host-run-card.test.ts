import { ChildProcess, execFileSync, spawn } from 'child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs'
import os from 'os'
import path from 'path'

import { parseJSON } from '~/common/utils/json-parse'

const WRAPPER = path.join(__dirname, 'host-run-card.sh')
const RUN_ID = '00000000-0000-4000-8000-000000000001'
const BUCKET = 'test-evidence'

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
    mkdir -p "$(dirname "$target")"
    cat >"$target"
fi
`

const FAKE_PNPM = `#!/usr/bin/env bash
run="$XDG_CACHE_HOME/posthog-scenarios/$SCENARIO_RUN_ID"
mkdir -p "$run"
echo '{"phase":"drive"}' >"$run/result.json"
if [ -n "\${FAKE_CARD_HANGS:-}" ]; then
    trap 'echo interrupted >"$run/interrupted"; exit 2' TERM
    touch "$run/running"
    while :; do sleep 0.1; done
fi
exit "\${FAKE_CARD_EXIT:-0}"
`

describe('host-run-card.sh', () => {
    let dir: string

    const s3 = (key: string): string => path.join(dir, 's3', BUCKET, 'runs', RUN_ID, key)

    function start(env: NodeJS.ProcessEnv): ChildProcess {
        const bin = path.join(dir, 'bin')
        mkdirSync(bin)
        writeFileSync(path.join(bin, 'aws'), FAKE_AWS, { mode: 0o755 })
        writeFileSync(path.join(bin, 'pnpm'), FAKE_PNPM, { mode: 0o755 })
        return spawn('bash', [WRAPPER], {
            env: {
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
    ])('marks done with the runner exit code when %s', async (_, env, exitCode, uploaded) => {
        await exited(start(env))

        expect(existsSync(s3('host/started'))).toBe(true)
        expect(parseJSON(readFileSync(s3('host/done'), 'utf8'))).toMatchObject({ exitCode, uploaded })
        expect(existsSync(s3('evidence/run/result.json'))).toBe(uploaded)
    })

    it('stops the card on SIGTERM and still uploads its partial evidence with checksums', async () => {
        const wrapper = start({ FAKE_CARD_HANGS: '1' })
        const done = exited(wrapper)
        await whenExists(path.join(dir, 'host', 'cache', 'posthog-scenarios', RUN_ID, 'running'))

        wrapper.kill('SIGTERM')
        await done

        expect(parseJSON(readFileSync(s3('host/done'), 'utf8'))).toMatchObject({ exitCode: 2, uploaded: true })
        expect(readFileSync(s3('evidence/run/interrupted'), 'utf8')).toBe('interrupted\n')
        expect(() =>
            execFileSync('sha256sum', ['--check', '--strict', 'SHA256SUMS'], { cwd: s3('evidence') })
        ).not.toThrow()
    })
})
