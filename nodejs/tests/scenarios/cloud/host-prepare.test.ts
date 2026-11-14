import { spawnSync } from 'child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'fs'
import os from 'os'
import path from 'path'
import { Client } from 'pg'

import { parseJSON } from '~/common/utils/json-parse'

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

const CLUSTER = '@scn.cluster.example.com:5432/cyclotron_node?sslmode=require'

const LOCAL_SQLX = `#!/usr/bin/env bash
args=()
for arg in "$@"; do
    args+=("\${arg/"$CLUSTER"/"@localhost:5432/$LOCAL_DATABASE?sslmode=disable"}")
done
exec "$REAL_SQLX" "\${args[@]}"
`

const FAKE_PNPM = `#!/usr/bin/env bash
while [ $# -gt 0 ]; do
    case $1 in
    --dir) dir=$2 && shift ;;
    exec) [ "$2" = tsx ] && entry=$3 && shift 2 ;;
    --profile) profile=$2 && shift ;;
    seed-backlog) command=$1 ;;
    esac
    shift
done
echo 'seed step output'
[ "\${FAKE_SEED_EXIT:-0}" = 0 ] || exit "$FAKE_SEED_EXIT"
program=$(cd "\${dir:-.}" && realpath -e "\${entry:-}") || exit 2
jq -n --arg database "$CYCLOTRON_NODE_DATABASE_URL" --arg manifest "$SCENARIO_RUN_MANIFEST" --arg program "$program" \\
    --arg command "\${command:-}" --arg profile "\${profile:-}" '{$database, $manifest, $program, $command, $profile}' >"$FAKE_CALLS/seeded"
`

const ADMIN_URL = 'postgres://posthog:posthog@localhost:5432/postgres'
const CLUSTER_USER = 'scn admin'
const CLUSTER_PASSWORD = 'p@ss/w:rd%'
const MIGRATIONS = path.join(REPO, 'rust', 'cyclotron-node-migrations')

async function onPostgres<T>(url: string, work: (client: Client) => Promise<T>): Promise<T> {
    const client = new Client({ connectionString: url })
    await client.connect()
    try {
        return await work(client)
    } finally {
        await client.end()
    }
}

describe('host-prepare.sh', () => {
    let dir: string
    let database: string
    const realSqlx = spawnSync('bash', ['-c', 'command -v sqlx'], { encoding: 'utf8' }).stdout.trim()

    const recorded = (tool: string): unknown =>
        existsSync(path.join(dir, 'calls', tool))
            ? parseJSON(readFileSync(path.join(dir, 'calls', tool), 'utf8'))
            : undefined

    function prepareHost(env: NodeJS.ProcessEnv): number | null {
        const bin = path.join(dir, 'bin')
        mkdirSync(bin)
        mkdirSync(path.join(dir, 'calls'))
        mkdirSync(path.join(dir, 'host', 'input'), { recursive: true })
        writeFileSync(path.join(bin, 'aws'), FAKE_AWS, { mode: 0o755 })
        writeFileSync(path.join(bin, 'sqlx'), LOCAL_SQLX, { mode: 0o755 })
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
                REAL_SQLX: realSqlx,
                CLUSTER,
                LOCAL_DATABASE: database,
                ...env,
            },
            stdio: 'ignore',
        }).status
    }

    beforeAll(async () => {
        expect(realSqlx).not.toBe('')
        await onPostgres(ADMIN_URL, async (client) => {
            const { rowCount } = await client.query('SELECT 1 FROM pg_roles WHERE rolname = $1', [CLUSTER_USER])
            const verb = rowCount ? 'ALTER' : 'CREATE'
            const password = await client.query('SELECT quote_literal($1) AS literal', [CLUSTER_PASSWORD])
            await client.query(`${verb} ROLE "${CLUSTER_USER}" LOGIN PASSWORD ${password.rows[0].literal}`)
        })
    })

    beforeEach(async () => {
        dir = mkdtempSync(path.join(os.tmpdir(), 'scenario-prepare-'))
        database = `test_scenario_prepare_${process.pid}_${Date.now()}`
        await onPostgres(ADMIN_URL, (client) => client.query(`CREATE DATABASE ${database} OWNER "${CLUSTER_USER}"`))
    })

    afterEach(async () => {
        rmSync(dir, { recursive: true, force: true })
        await onPostgres(ADMIN_URL, (client) => client.query(`DROP DATABASE IF EXISTS ${database} WITH (FORCE)`))
    })

    it('migrates and seeds the run cluster with its encoded credentials', async () => {
        expect(prepareHost({})).toBe(0)

        const applied = await onPostgres(`postgres://posthog:posthog@localhost:5432/${database}`, (client) =>
            client.query<{ version: string }>(
                'SELECT version::text FROM _sqlx_migrations WHERE success ORDER BY version'
            )
        )
        expect(applied.rows.map(({ version }) => version)).toEqual(
            readdirSync(MIGRATIONS)
                .filter((file) => file.endsWith('.sql'))
                .map((file) => file.split('_')[0])
                .sort()
        )
        expect(recorded('seeded')).toEqual({
            database: URL,
            manifest: path.join(dir, 'host', 'input', 'manifest.json'),
            program: path.join(REPO, 'nodejs', 'tests', 'scenarios', 'main.ts'),
            command: 'seed-backlog',
            profile: path.join(dir, 'host', 'input', 'runner-profile.yaml'),
        })
    })

    it.each([
        ['the migration fails', { LOCAL_DATABASE: 'test_scenario_prepare_missing' }, 'test_scenario_prepare_missing'],
        ['the seed fails', { FAKE_SEED_EXIT: '1' }, 'seed step output'],
    ])('fails and uploads its log when %s', (_, env, output) => {
        expect(prepareHost(env)).not.toBe(0)

        expect(readFileSync(path.join(dir, 's3', BUCKET, 'runs', RUN_ID, 'host', 'prepare.log'), 'utf8')).toContain(
            output
        )
        expect(recorded('seeded')).toBeUndefined()
    })
})
