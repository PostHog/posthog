import { spawnSync } from 'child_process'
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'fs'
import os from 'os'
import path from 'path'
import { Client } from 'pg'
import { stringify } from 'yaml'

import { residentBacklogOf } from '../backlog/backlog'
import { defaultStateDir } from '../environment/environment'
import { residentBacklogIntact } from '../judge/invariants'

const SCRIPT = path.join(__dirname, 'host-prepare.sh')
const REPO = path.resolve(__dirname, '../../../..')
const RUN_ID = '00000000-0000-4000-8000-000000000001'
const BUCKET = 'test-evidence'

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

const CLUSTER_DATABASE = '@scn.cluster.example.com:5432/cyclotron_node'

const LOCAL_SQLX = `#!/usr/bin/env bash
args=()
for arg in "$@"; do
    args+=("\${arg/"$CLUSTER"/"@localhost:5432/$LOCAL_DATABASE?sslmode=disable"}")
done
exec "$REAL_SQLX" "\${args[@]}"
`

const LOCAL_PNPM = `#!/usr/bin/env bash
export CYCLOTRON_NODE_DATABASE_URL="\${CYCLOTRON_NODE_DATABASE_URL/"$CLUSTER_DATABASE"*/"@localhost:5432/$LOCAL_DATABASE?sslmode=disable"}"
exec "$REAL_PNPM" "$@"
`

const BACKLOG = {
    teams: 1,
    jobs: { hogflow: 20, email: 10 },
    stateBytes: { p50: 100, p90: 200, p99: 400 },
    compressibility: 0.5,
    parkFor: '10080m',
    tolerance: 0.01,
}

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
    const realPnpm = spawnSync('bash', ['-c', 'command -v pnpm'], { encoding: 'utf8' }).stdout.trim()

    function prepareHost(env: NodeJS.ProcessEnv, backlog: object | null = BACKLOG): number | null {
        const bin = path.join(dir, 'bin')
        const input = path.join(dir, 'host', 'input')
        mkdirSync(bin)
        mkdirSync(input, { recursive: true })
        writeFileSync(path.join(input, 'manifest.json'), JSON.stringify({ runId: RUN_ID }))
        writeFileSync(
            path.join(input, 'runner-profile.yaml'),
            stringify({ name: 'resident', settings: {}, ...(backlog ? { backlog } : {}) })
        )
        writeFileSync(path.join(bin, 'aws'), FAKE_AWS, { mode: 0o755 })
        writeFileSync(path.join(bin, 'sqlx'), LOCAL_SQLX, { mode: 0o755 })
        writeFileSync(path.join(bin, 'pnpm'), LOCAL_PNPM, { mode: 0o755 })
        return spawnSync('bash', [SCRIPT], {
            env: {
                PATH: `${bin}:${process.env.PATH}`,
                HOME: dir,
                ...Object.fromEntries(Object.entries(process.env).filter(([name]) => /^(LD|FLOX)_/.test(name))),
                COREPACK_HOME: process.env.COREPACK_HOME ?? path.join(os.homedir(), '.cache', 'node', 'corepack'),
                SCENARIO_RUN_ID: RUN_ID,
                SCENARIO_EVIDENCE_BUCKET: BUCKET,
                SCENARIO_HOST_ROOT: path.join(dir, 'host'),
                FAKE_S3: path.join(dir, 's3'),
                REAL_SQLX: realSqlx,
                REAL_PNPM: realPnpm,
                CLUSTER: `${CLUSTER_DATABASE}?sslmode=verify-full&sslrootcert=${path.join(dir, 'host', 'rds-ca.pem')}`,
                CLUSTER_DATABASE,
                LOCAL_DATABASE: database,
                ...env,
            },
            stdio: 'ignore',
        }).status
    }

    beforeAll(async () => {
        expect(realSqlx).not.toBe('')
        expect(realPnpm).not.toBe('')
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

    it('migrates and seeds the run cluster with its encoded credentials, recording the backlog where the card reads it', async () => {
        expect(prepareHost({})).toBe(0)

        const cardStateDir = defaultStateDir({ XDG_CACHE_HOME: path.join(dir, 'host', 'cache') })
        const resident = await residentBacklogOf(
            { name: 'resident', backlog: BACKLOG },
            cardStateDir,
            `postgres://posthog:posthog@localhost:5432/${database}`
        )
        expect(
            residentBacklogIntact.check(
                { journal: [], truth: [], fetchRetries: 0, resident, janitorResets: 0 },
                undefined
            )
        ).toMatchObject({ passed: true })

        const { applied, seeded } = await onPostgres(
            `postgres://posthog:posthog@localhost:5432/${database}`,
            async (client) => ({
                applied: await client.query<{ version: string }>(
                    'SELECT version::text FROM _sqlx_migrations WHERE success ORDER BY version'
                ),
                seeded: await client.query<{ queue: string; rows: number }>(
                    'SELECT queue_name AS queue, count(*)::int AS rows FROM cyclotron_jobs GROUP BY 1 ORDER BY 1'
                ),
            })
        )
        expect(applied.rows.map(({ version }) => version)).toEqual(
            readdirSync(MIGRATIONS)
                .filter((file) => file.endsWith('.sql'))
                .map((file) => file.split('_')[0])
                .sort()
        )
        expect(Object.fromEntries(seeded.rows.map(({ queue, rows }) => [queue, rows]))).toEqual(BACKLOG.jobs)
    }, 120_000)

    it.each<[string, NodeJS.ProcessEnv, object | null, string]>([
        [
            'the migration fails',
            { LOCAL_DATABASE: 'test_scenario_prepare_missing' },
            BACKLOG,
            'test_scenario_prepare_missing',
        ],
        ['the seed fails', {}, null, 'has no backlog to seed'],
    ])(
        'fails and uploads its log when %s',
        (_, env, backlog, output) => {
            expect(prepareHost(env, backlog)).not.toBe(0)

            expect(readFileSync(path.join(dir, 's3', BUCKET, 'runs', RUN_ID, 'host', 'prepare.log'), 'utf8')).toContain(
                output
            )
        },
        120_000
    )
})
