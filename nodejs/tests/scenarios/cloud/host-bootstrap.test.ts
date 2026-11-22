import { spawnSync } from 'child_process'
import { createHash } from 'crypto'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs'
import os from 'os'
import path from 'path'
import { parse } from 'yaml'

const BOOTSTRAP = path.join(__dirname, 'host-bootstrap.sh')
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

    it.each<[string, { runId: string; stored: string }, boolean]>([
        ['inputs that match the manifest', { runId: RUN_ID, stored: '{"card":"failover"}' }, true],
        ['an input whose bytes differ from the manifest', { runId: RUN_ID, stored: '{"card":"other"}' }, false],
        ['a manifest of another run', { runId: OTHER_RUN_ID, stored: '{"card":"failover"}' }, false],
    ])('checks the run inputs before it installs the toolchain, given %s', (_, { runId, stored }, verified) => {
        const prefix = path.join(bucket, 'runs', RUN_ID)
        mkdirSync(path.join(prefix, 'input'), { recursive: true })
        writeFileSync(
            path.join(prefix, 'input', 'manifest.json'),
            JSON.stringify({ runId, inputs: { 'profile.json': sha256('{"card":"failover"}') } })
        )
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

        const result = spawnSync('bash', [BOOTSTRAP], { env: env(), encoding: 'utf8' })

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
