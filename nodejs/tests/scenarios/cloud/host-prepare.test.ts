import { spawnSync } from 'child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs'
import os from 'os'
import path from 'path'

const SCRIPT = path.join(__dirname, 'host-prepare.sh')
const REPO = path.resolve(__dirname, '../../../..')
const RUN_ID = '00000000-0000-4000-8000-000000000001'
const BUCKET = 'test-evidence'
const URL = 'postgres://scn%20admin:p%40ss%2Fw%3Ard%25@scn.cluster.example.com:5432/cyclotron_node?sslmode=require'

const FAKE_AWS = `#!/usr/bin/env bash
case "$1 $2" in
"rds describe-db-clusters")
    echo '{"Endpoint":"scn.cluster.example.com","MasterUserSecret":{"SecretArn":"arn:example:secret"}}' ;;
"secretsmanager get-secret-value")
    echo '{"username":"scn admin","password":"p@ss/w:rd%"}' ;;
"s3 cp")
    key="\${@: -1}"
    target="$FAKE_S3/\${key#s3://}"
    mkdir -p "$(dirname "$target")"
    cp "$4" "$target" ;;
*) exit 2 ;;
esac
`

const FAKE_SQLX = `#!/usr/bin/env bash
printf '%s\\n' "$@" >"$FAKE_CALLS/sqlx"
echo 'migration step output' >&2
exit "\${FAKE_MIGRATE_EXIT:-0}"
`

const FAKE_PNPM = `#!/usr/bin/env bash
printf '%s\\n' "$CYCLOTRON_NODE_DATABASE_URL" "$SCENARIO_RUN_MANIFEST" "$@" >"$FAKE_CALLS/pnpm"
echo 'seed step output'
exit "\${FAKE_SEED_EXIT:-0}"
`

describe('host-prepare.sh', () => {
    let dir: string

    const calls = (tool: string): string[] =>
        existsSync(path.join(dir, 'calls', tool))
            ? readFileSync(path.join(dir, 'calls', tool), 'utf8')
                  .trimEnd()
                  .split('\n')
            : []

    function prepareHost(env: NodeJS.ProcessEnv): number | null {
        const bin = path.join(dir, 'bin')
        mkdirSync(bin)
        mkdirSync(path.join(dir, 'calls'))
        mkdirSync(path.join(dir, 'host', 'input'), { recursive: true })
        writeFileSync(path.join(bin, 'aws'), FAKE_AWS, { mode: 0o755 })
        writeFileSync(path.join(bin, 'sqlx'), FAKE_SQLX, { mode: 0o755 })
        writeFileSync(path.join(bin, 'pnpm'), FAKE_PNPM, { mode: 0o755 })
        return spawnSync('bash', [SCRIPT], {
            env: {
                PATH: `${bin}:${process.env.PATH}`,
                HOME: dir,
                SCENARIO_RUN_ID: RUN_ID,
                SCENARIO_EVIDENCE_BUCKET: BUCKET,
                SCENARIO_HOST_ROOT: path.join(dir, 'host'),
                FAKE_S3: path.join(dir, 's3'),
                FAKE_CALLS: path.join(dir, 'calls'),
                ...env,
            },
            stdio: 'ignore',
        }).status
    }

    beforeEach(() => {
        dir = mkdtempSync(path.join(os.tmpdir(), 'scenario-prepare-'))
    })

    afterEach(() => rmSync(dir, { recursive: true, force: true }))

    it('migrates and seeds the run cluster with its encoded credentials', () => {
        expect(prepareHost({})).toBe(0)

        const source = calls('sqlx')[calls('sqlx').indexOf('--source') + 1]
        expect(calls('sqlx')).toEqual(['migrate', 'run', '-D', URL, '--source', source])
        expect(existsSync(source)).toBe(true)
        expect(path.relative(REPO, source)).toBe('rust/cyclotron-node-migrations')
        expect(calls('pnpm')).toEqual([
            URL,
            path.join(dir, 'host', 'input', 'manifest.json'),
            '--dir',
            path.join(REPO, 'nodejs'),
            'exec',
            'tsx',
            'tests/scenarios/main.ts',
            'seed-backlog',
            '--profile',
            path.join(dir, 'host', 'input', 'runner-profile.yaml'),
        ])
    })

    it.each([
        ['the migration fails', { FAKE_MIGRATE_EXIT: '1' }, 'migration step output', false],
        ['the seed fails', { FAKE_SEED_EXIT: '1' }, 'seed step output', true],
    ])('fails and uploads its log when %s', (_, env, output, seeded) => {
        expect(prepareHost(env)).not.toBe(0)

        expect(readFileSync(path.join(dir, 's3', BUCKET, 'runs', RUN_ID, 'host', 'prepare.log'), 'utf8')).toContain(
            output
        )
        expect(calls('pnpm').length > 0).toBe(seeded)
    })
})
