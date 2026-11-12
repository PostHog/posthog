import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'

import { deriveSchemaRequirements } from './derive-requirements'

const FIXTURE_FILES: Record<string, string> = {
    'posthog/apps.py': 'class PostHogConfig(AppConfig):\n    name = "posthog"\n',
    'posthog/migrations/0001_initial.py': 'migrations.CreateModel(\n    name="Team",\n    fields=[],\n)\n',
    'posthog/migrations/0002_team_flag.py': 'migrations.AddField(model_name="team", name="flag")\n',
    'posthog/migrations/max_migration.txt': '0002_team_flag\n',

    // The label override makes the table posthog_session_session, not session_session.
    'posthog/session/apps.py':
        'class SessionConfig(AppConfig):\n    name = "posthog.session"\n    label = "posthog_session"\n',
    'posthog/session/migrations/0001_initial.py': 'migrations.CreateModel(name="Session", fields=[])\n',
    'posthog/session/migrations/max_migration.txt': '0001_initial\n',

    'posthog/clickhouse/migrations/0001_initial.py': 'migrations.CreateModel(name="Events", fields=[])\n',
    'posthog/clickhouse/migrations/max_migration.txt': '0001_initial\n',

    'products/surveys/backend/apps.py':
        'class SurveysConfig(AppConfig):\n    name = "products.surveys.backend"\n    label = "surveys"\n',
    'products/surveys/backend/migrations/0001_initial.py':
        'migrations.CreateModel(\n    name="Survey",\n    fields=[],\n    options={"db_table": "posthog_survey"},\n)\n',
    'products/surveys/backend/migrations/max_migration.txt': '0001_initial\n',

    'products/legacy/backend/apps.py':
        'class LegacyConfig(AppConfig):\n    name = "products.legacy.backend"\n    label = "legacy"\n',
    'products/legacy/backend/migrations/0001_initial.py': 'migrations.CreateModel(name="Widget", fields=[])\n',
    'products/legacy/backend/migrations/0002_move_widget.py': 'migrations.DeleteModel(name="Widget")\n',
    'products/legacy/backend/migrations/max_migration.txt': '0002_move_widget\n',

    'products/widgets/backend/apps.py':
        'class WidgetsConfig(AppConfig):\n    name = "products.widgets.backend"\n    label = "widgets"\n',
    'products/widgets/backend/migrations/0001_initial.py': 'migrations.CreateModel(name="Widget", fields=[])\n',
    'products/widgets/backend/migrations/0002_widget_table.py':
        'migrations.AlterModelTable(name="widget", table="legacy_widget")\n',
    'products/widgets/backend/migrations/max_migration.txt': '0002_widget_table\n',

    'products/tracing/backend/apps.py':
        'class TracingConfig(AppConfig):\n    name = "products.tracing.backend"\n    label = "tracing"\n',
    'products/tracing/backend/migrations/0001_squash_initial.py':
        'class Migration(migrations.Migration):\n' +
        '    replaces = [\n        ("tracing", "0001_initial"),\n        ("tracing", "0002_span_kind"),\n    ]\n' +
        '    operations = [migrations.CreateModel(name="Span", fields=[])]\n',
    'products/tracing/backend/migrations/max_migration.txt': '0001_squash_initial\n',

    'products/stamphog/backend/apps.py':
        'class StamphogConfig(AppConfig):\n    name = "products.stamphog.backend"\n    label = "stamphog"\n',
    'products/stamphog/backend/migrations/0001_initial.py': 'migrations.CreateModel(name="Review", fields=[])\n',
    'products/stamphog/backend/migrations/0002_take_widget.py':
        'migrations.CreateModel(name="Widget", fields=[], options={"db_table": "legacy_widget"})\n',
    'products/stamphog/backend/migrations/max_migration.txt': '0002_take_widget\n',
    'products/db_routing.yaml': 'routes:\n    - app_label: stamphog\n      database: stamphog\n',

    'products/replay/backend/apps.py':
        'class ReplayConfig(AppConfig):\n    name = "products.replay.backend"\n    label = "replay"\n',
    'products/replay/backend/migrations/0001_initial.py': 'migrations.CreateModel(name="Lens", fields=[])\n',
    'products/replay/backend/migrations/0002_rename.py':
        'migrations.RenameModel(old_name="Lens", new_name="Observation")\n',
    'products/replay/backend/migrations/max_migration.txt': '0002_rename\n',

    'products/rawsql/backend/apps.py':
        'class RawSqlConfig(AppConfig):\n    name = "products.rawsql.backend"\n    label = "rawsql"\n',
    'products/rawsql/backend/migrations/0001_initial.py':
        '# A CREATE TABLE for each team would be slow.\n' +
        'migrations.RunSQL("CREATE TABLE IF NOT EXISTS rawsql_store (id bigint)")\n',
    'products/rawsql/backend/migrations/max_migration.txt': '0001_initial\n',

    'products/unused/backend/apps.py':
        'class UnusedConfig(AppConfig):\n    name = "products.unused.backend"\n    label = "unused"\n',
    'products/unused/backend/migrations/0001_initial.py': 'migrations.CreateModel(name="Thing", fields=[])\n',
    'products/unused/backend/migrations/max_migration.txt': '0001_initial\n',

    'rust/persons_migrations/20250101000001_initial.sql':
        'CREATE TABLE IF NOT EXISTS posthog_persons_row (id bigint);\n',
    'rust/cyclotron-node-migrations/20260101000001_initial.sql':
        'CREATE TABLE IF NOT EXISTS cyclotron_jobs (id uuid);\n',
    // These versions create no table, but they change cyclotron_jobs, which Node reads.
    'rust/cyclotron-node-migrations/20260201000001_add_index.sql': 'CREATE INDEX idx_jobs ON cyclotron_jobs (id);\n',
    'rust/cyclotron-node-migrations/20260301000001_add.batch.index.sql':
        'CREATE INDEX idx_batch ON cyclotron_jobs (id);\n',
    'rust/cyclotron-node-migrations/20260301000001_add.batch.index.down.sql': 'DROP INDEX idx_batch;\n',
    // Node never reads cyclotron_attachments, so neither version is a requirement.
    'rust/cyclotron-node-migrations/20260401000001_add_attachments.sql':
        'CREATE TABLE cyclotron_attachments (id uuid);\n',
    'rust/cyclotron-node-migrations/20260501000001_drop_attachments.sql':
        'DROP TABLE IF EXISTS cyclotron_attachments;\n',
    // Names no table, but the index may be on a table Node reads.
    'rust/cyclotron-node-migrations/20260601000001_drop_index.sql': 'DROP INDEX IF EXISTS idx_jobs;\n',
    'rust/behavioral_cohorts_migrations/20260301000001_initial.sql': 'CREATE TABLE cohort_membership (id bigint);\n',

    'nodejs/src/reader.ts': [
        "import { PostgresUse } from './postgres'",
        'const glob = `${KEY}/*`',
        "const a = 'SELECT * FROM posthog_team'",
        "const b = 'SELECT * FROM posthog_session_session'",
        "const c = 'SELECT * FROM posthog_survey'",
        "const d = 'SELECT * FROM legacy_widget'",
        "const e = 'SELECT * FROM tracing_span'",
        "const f = 'SELECT * FROM clickhouse_events'",
        'const g = \'SELECT * FROM posthog_team AS "t", "public"."stamphog_review" r\'',
        "const i = 'SELECT * FROM cyclotron_jobs'",
        'for (const row of rows) {}',
        "const j = 'SELECT * FROM replay_observation'",
        "const k = 'INSERT INTO RAWSQL_STORE VALUES (1)'",
        'const l = "SELECT \'//\' AS marker FROM posthog_ghost"',
        '// Rows move from posthog_ghost_comment once the job runs.',
    ].join('\n'),
    'nodejs/src/clickhouse-reader.ts':
        "import { ClickHouseClient } from '@clickhouse/client'\nconst q = 'SELECT * FROM tracing_spans_distributed'\n",
    'nodejs/src/pool-reader.ts': "/* note */ const q = 'SELECT * FROM posthog_pool_ghost'\n/* next */\n",
    'nodejs/src/reader.test.ts': "const h = 'SELECT * FROM unused_thing'\n",
}

describe('deriveSchemaRequirements', () => {
    let repoRoot: string

    beforeAll(() => {
        repoRoot = mkdtempSync(path.join(tmpdir(), 'schema-check-'))
        for (const [relativePath, content] of Object.entries(FIXTURE_FILES)) {
            const filePath = path.join(repoRoot, relativePath)
            mkdirSync(path.dirname(filePath), { recursive: true })
            writeFileSync(filePath, content)
        }
    })

    afterAll(() => {
        rmSync(repoRoot, { recursive: true, force: true })
    })

    it('requires the leaf of every Django app and sqlx database whose tables nodejs/src reads', () => {
        const { requirements, tablesByRequirement, findings } = deriveSchemaRequirements(repoRoot)

        expect(requirements).toEqual([
            { kind: 'django', database: 'default', app: 'legacy', migration: '0002_move_widget' },
            { kind: 'django', database: 'default', app: 'posthog', migration: '0002_team_flag' },
            { kind: 'django', database: 'default', app: 'posthog_session', migration: '0001_initial' },
            { kind: 'django', database: 'default', app: 'rawsql', migration: '0001_initial' },
            { kind: 'django', database: 'default', app: 'replay', migration: '0002_rename' },
            { kind: 'django', database: 'default', app: 'surveys', migration: '0001_initial' },
            {
                kind: 'django',
                database: 'default',
                app: 'tracing',
                migration: '0001_squash_initial',
                replaces: ['0001_initial', '0002_span_kind'],
            },
            { kind: 'django', database: 'default', app: 'widgets', migration: '0002_widget_table' },
            {
                kind: 'sqlx',
                database: 'cyclotron-node',
                versions: [20260101000001, 20260201000001, 20260301000001, 20260601000001],
            },
        ])
        expect(Object.fromEntries(tablesByRequirement)).toEqual({
            legacy: ['legacy_widget'],
            posthog: ['posthog_team'],
            posthog_session: ['posthog_session_session'],
            rawsql: ['rawsql_store'],
            replay: ['replay_observation'],
            surveys: ['posthog_survey'],
            tracing: ['tracing_span'],
            widgets: ['legacy_widget'],
            'sqlx:cyclotron-node': ['cyclotron_jobs'],
        })
        // clickhouse_events has no app prefix, so it is out of scope. The comment adds no reference.
        expect(findings).toEqual([
            'legacy_widget: owned by stamphog, which products/db_routing.yaml sends to a product database',
            'posthog_ghost: no scanned migration creates it, although its name starts with posthog_',
            'posthog_pool_ghost: no scanned migration creates it, although its name starts with posthog_',
            'stamphog_review: owned by stamphog, which products/db_routing.yaml sends to a product database',
        ])
    })

    it('finds the workflows config, team and cyclotron job tables on the real repo, and no uncovered table', () => {
        const { tablesByRequirement, findings } = deriveSchemaRequirements(path.resolve(__dirname, '../../..'))

        expect(tablesByRequirement.get('workflows')).toContain('workflows_teamworkflowsconfig')
        expect(tablesByRequirement.get('posthog')).toContain('posthog_team')
        expect(tablesByRequirement.get('sqlx:cyclotron-node')).toContain('cyclotron_jobs')
        expect(findings).toEqual([])
    })
})
