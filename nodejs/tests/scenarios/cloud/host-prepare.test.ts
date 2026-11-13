import { spawnSync } from 'child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs'
import os from 'os'
import path from 'path'

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

const FAKE_SQLX = `#!/usr/bin/env bash
[ "$1 $2" = "migrate run" ] || exit 2
shift 2
database=\${DATABASE_URL:-}
while [ $# -gt 0 ]; do
    case $1 in
    -D | --database-url) database=$2 && shift ;;
    --source) source=$2 && shift ;;
    esac
    shift
done
echo 'migration step output' >&2
[ "\${FAKE_MIGRATE_EXIT:-0}" = 0 ] || exit "$FAKE_MIGRATE_EXIT"
jq -n --arg database "$database" --arg source "$(realpath "$source")" '{$database, $source}' >"$FAKE_CALLS/migrated"
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

describe('host-prepare.sh', () => {
    let dir: string

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

        expect(recorded('migrated')).toEqual({
            database: URL,
            source: path.join(REPO, 'rust', 'cyclotron-node-migrations'),
        })
        expect(recorded('seeded')).toEqual({
            database: URL,
            manifest: path.join(dir, 'host', 'input', 'manifest.json'),
            program: path.join(REPO, 'nodejs', 'tests', 'scenarios', 'main.ts'),
            command: 'seed-backlog',
            profile: path.join(dir, 'host', 'input', 'runner-profile.yaml'),
        })
    })

    it.each([
        ['the migration fails', { FAKE_MIGRATE_EXIT: '1' }, 'migration step output'],
        ['the seed fails', { FAKE_SEED_EXIT: '1' }, 'seed step output'],
    ])('fails and uploads its log when %s', (_, env, output) => {
        expect(prepareHost(env)).not.toBe(0)

        expect(readFileSync(path.join(dir, 's3', BUCKET, 'runs', RUN_ID, 'host', 'prepare.log'), 'utf8')).toContain(
            output
        )
        expect(recorded('seeded')).toBeUndefined()
    })
})
