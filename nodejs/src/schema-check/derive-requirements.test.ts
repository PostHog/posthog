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
    'products/stamphog/backend/migrations/max_migration.txt': '0001_initial\n',
    'products/db_routing.yaml': 'routes:\n    - app_label: stamphog\n      database: stamphog\n',

    'products/unused/backend/apps.py':
        'class UnusedConfig(AppConfig):\n    name = "products.unused.backend"\n    label = "unused"\n',
    'products/unused/backend/migrations/0001_initial.py': 'migrations.CreateModel(name="Thing", fields=[])\n',
    'products/unused/backend/migrations/max_migration.txt': '0001_initial\n',

    'nodejs/src/reader.ts': [
        "const a = 'SELECT * FROM posthog_team'",
        "const b = 'SELECT * FROM posthog_session_session'",
        "const c = 'SELECT * FROM posthog_survey'",
        "const d = 'SELECT * FROM legacy_widget'",
        "const e = 'SELECT * FROM tracing_span'",
        "const f = 'SELECT * FROM clickhouse_events'",
        "const g = 'SELECT * FROM stamphog_review'",
    ].join('\n'),
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

    it('requires the leaf of every Postgres app whose tables nodejs/src reads', () => {
        const { requirements, tablesByApp } = deriveSchemaRequirements(repoRoot)

        expect(requirements).toEqual([
            { database: 'default', app: 'legacy', migration: '0002_move_widget' },
            { database: 'default', app: 'posthog', migration: '0002_team_flag' },
            { database: 'default', app: 'posthog_session', migration: '0001_initial' },
            { database: 'default', app: 'surveys', migration: '0001_initial' },
            {
                database: 'default',
                app: 'tracing',
                migration: '0001_squash_initial',
                replaces: ['0001_initial', '0002_span_kind'],
            },
            { database: 'default', app: 'widgets', migration: '0002_widget_table' },
        ])
        expect(Object.fromEntries(tablesByApp)).toEqual({
            legacy: ['legacy_widget'],
            posthog: ['posthog_team'],
            posthog_session: ['posthog_session_session'],
            surveys: ['posthog_survey'],
            tracing: ['tracing_span'],
            widgets: ['legacy_widget'],
        })
    })

    it('finds the workflows config and team tables on the real repo', () => {
        const { tablesByApp } = deriveSchemaRequirements(path.resolve(__dirname, '../../..'))

        expect(tablesByApp.get('workflows')).toContain('workflows_teamworkflowsconfig')
        expect(tablesByApp.get('posthog')).toContain('posthog_team')
    })
})
