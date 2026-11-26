import { spawnSync } from 'child_process'
import { createHash } from 'crypto'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs'
import os from 'os'
import path from 'path'
import { parse } from 'yaml'

const BOOTSTRAP = path.join(__dirname, 'host-bootstrap.sh')
const DRY_RUN = path.join(__dirname, 'host-dry-run.sh')
const TEMPLATE = path.join(__dirname, 'run-stack.yaml')
const RUN_ID = '00000000-0000-4000-8000-000000000001'
const OTHER_RUN_ID = '00000000-0000-4000-8000-000000000002'
const BUCKET = 'test-evidence'
const HOUR_MS = 60 * 60 * 1000

const sha256 = (body: string): string => createHash('sha256').update(body).digest('hex')

describe('host boot', () => {
    let dir: string
    let bin: string
    let bucket: string

    const tool = (name: string, body: string): void =>
        writeFileSync(path.join(bin, name), `#!/usr/bin/env bash\n${body}\n`, { mode: 0o755 })

    const env = (): NodeJS.ProcessEnv => ({
        PATH: `${bin}:/usr/bin:/bin`,
        HOME: dir,
        SCENARIO_RUN_ID: RUN_ID,
        SCENARIO_EVIDENCE_BUCKET: BUCKET,
        SCENARIO_BOOTSTRAP_LOG: path.join(dir, 'bootstrap.log'),
        SCENARIO_HOST_ROOT: path.join(dir, 'host'),
        SCENARIO_HOSTS_FILE: path.join(dir, 'hosts'),
    })

    const poweredOff = (): boolean => existsSync(path.join(dir, 'powered-off'))

    beforeEach(() => {
        dir = mkdtempSync(path.join(os.tmpdir(), 'host-boot-'))
        bin = path.join(dir, 'bin')
        bucket = path.join(dir, 'bucket')
        mkdirSync(bin)
        tool('poweroff', `touch "${dir}/powered-off"`)
        tool('curl', `echo "$*" >>"${dir}/curl.log"\nexit 22`)
    })

    afterEach(() => rmSync(dir, { recursive: true, force: true }))

    it('powers the host off when the package install fails before the AWS CLI exists', () => {
        tool('apt-get', 'exit 100')

        const result = spawnSync('bash', [BOOTSTRAP], { env: env(), encoding: 'utf8' })

        expect(result.status).not.toBe(0)
        expect(poweredOff()).toBe(true)
    })

    it.each<[string, { runId: string; stored: string; admittedCard?: string }, boolean]>([
        ['inputs that match the manifest', { runId: RUN_ID, stored: '{"card":"failover"}' }, true],
        ['an input whose bytes differ from the manifest', { runId: RUN_ID, stored: '{"card":"other"}' }, false],
        ['a manifest of another run', { runId: OTHER_RUN_ID, stored: '{"card":"failover"}' }, false],
        [
            'a valid bundle whose manifest differs from the one admitted by the controller',
            { runId: RUN_ID, stored: '{"card":"failover"}', admittedCard: '{"card":"other"}' },
            false,
        ],
    ])('checks inputs before installing the toolchain, given %s', (_, { runId, stored, admittedCard }, verified) => {
        const prefix = path.join(bucket, 'runs', RUN_ID)
        mkdirSync(path.join(prefix, 'input'), { recursive: true })
        const manifestOf = (profile: string): string =>
            JSON.stringify({ runId, inputs: { 'profile.json': sha256(profile) } })
        writeFileSync(path.join(prefix, 'input', 'manifest.json'), manifestOf('{"card":"failover"}'))
        writeFileSync(path.join(prefix, 'input', 'profile.json'), stored)
        tool('apt-get', 'exit 0')
        tool(
            'aws',
            [
                'if [ "$1" = --version ]; then echo "aws-cli/2.22.0 Python/3.12.6 Linux/6.8.0 exe/x86_64"; exit 0; fi',
                '[ "$1 $2" = "s3 cp" ] || exit 1',
                'shift 2',
                'paths=()',
                'for arg in "$@"; do case "$arg" in --*) ;; *) paths+=("$arg") ;; esac; done',
                `src=\${paths[0]/s3:\\/\\/${BUCKET}/${bucket}}`,
                `dst=\${paths[1]/s3:\\/\\/${BUCKET}/${bucket}}`,
                'case " $* " in',
                '    *" --recursive "*) mkdir -p "$dst" && cp -R "$src/." "$dst/" ;;',
                '    *) mkdir -p "$(dirname "$dst")" && if [ "$src" = - ]; then cat >"$dst"; else cp "$src" "$dst"; fi ;;',
                'esac',
            ].join('\n')
        )

        const result = spawnSync('bash', [BOOTSTRAP], {
            env: {
                ...env(),
                SCENARIO_INPUT_MANIFEST_SHA256: sha256(manifestOf(admittedCard ?? '{"card":"failover"}')),
            },
            encoding: 'utf8',
        })

        expect(result.status).not.toBe(0)
        expect(existsSync(path.join(prefix, 'host', 'failed'))).toBe(true)
        expect(existsSync(path.join(prefix, 'host', 'ready'))).toBe(false)
        const downloads = existsSync(path.join(dir, 'curl.log')) ? readFileSync(path.join(dir, 'curl.log'), 'utf8') : ''
        expect(downloads.includes('https://nodejs.org/')).toBe(verified)
    })

    it("maps the stack's service names to this host, which no dev setup ran on", () => {
        const hosts = path.join(dir, 'hosts')
        writeFileSync(hosts, '127.0.0.1 localhost\n')
        tool('apt-get', 'exit 0')
        tool(
            'aws',
            'if [ "$1" = --version ]; then echo "aws-cli/2.22.0 Python/3.12.6 Linux/6.8.0 exe/x86_64"; exit 0; fi\nexit 1'
        )

        spawnSync('bash', [BOOTSTRAP], { env: env(), encoding: 'utf8' })

        const addressOf = (name: string): string[] =>
            readFileSync(hosts, 'utf8')
                .split('\n')
                .map((line) => line.split('#')[0].trim().split(/\s+/))
                .filter(([, ...names]) => names.includes(name))
                .map(([address]) => address)
        expect(['db', 'redis7', 'kafka', 'clickhouse'].map(addressOf)).toEqual([
            ['127.0.0.1'],
            ['127.0.0.1'],
            ['127.0.0.1'],
            ['127.0.0.1'],
        ])
    })

    it('passes the dry-run input manifest digest to the host container', () => {
        const input = path.join(dir, 'input')
        const work = path.join(dir, 'work')
        const containerArgs = path.join(dir, 'container-args')
        const manifest = JSON.stringify({ runId: RUN_ID, inputs: {} }, null, 2)
        mkdirSync(input)
        writeFileSync(path.join(input, 'manifest.json'), manifest)
        writeFileSync(path.join(input, 'cloud-profile.yaml'), 'engineVersion: "16.1"\n')
        tool('git', '[ "$3" = archive ] && exit 0\nPATH="/usr/bin:/bin" exec git "$@"')
        tool('curl', 'touch "$4"')
        tool(
            'sha256sum',
            'if [ "${1:-}" = --check ]; then cat >/dev/null; exit 0; fi\nPATH="/usr/bin:/bin" exec sha256sum "$@"'
        )
        tool('openssl', `touch "${work}/tls/ca.pem"`)
        tool('awk', 'echo 192.0.2.1')
        tool(
            'docker',
            `case "$1:$2" in
                info:--format) echo x86_64 ;;
                run:--name) printf '%s\\n' "$@" >"${containerArgs}" ;;
            esac`
        )

        const result = spawnSync('bash', [DRY_RUN, input, work], { env: env(), encoding: 'utf8' })

        expect(result.stderr).toBe('')
        expect(result.status).toBe(0)
        const digestArgs = readFileSync(containerArgs, 'utf8')
            .split('\n')
            .filter((arg, i, args) => args[i - 1] === '-e' && arg.startsWith('SCENARIO_INPUT_MANIFEST_SHA256='))
        expect(digestArgs).toEqual([`SCENARIO_INPUT_MANIFEST_SHA256=${sha256(manifest)}`])
    })

    it('powers the host off when the checkout of the run commit fails', () => {
        const template = parse(readFileSync(TEMPLATE, 'utf8'))
        const userData: string = template.Resources.Host.Properties.UserData['Fn::Base64']['Fn::Sub']
        const script = path.join(dir, 'user-data.sh')
        writeFileSync(
            script,
            userData
                .replaceAll('${ExpiresAt}', new Date(Date.now() + HOUR_MS).toISOString())
                .replaceAll('/opt/posthog', path.join(dir, 'checkout'))
        )
        tool('shutdown', 'exit 0')
        tool('git', '[ "$1" = init ] && exit 0\nexit 128')

        const result = spawnSync('bash', [script], { env: env(), encoding: 'utf8' })

        expect(result.status).not.toBe(0)
        expect(poweredOff()).toBe(true)
    })
})
