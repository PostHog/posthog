from unittest.mock import MagicMock

from django.db import migrations, models

from parameterized import parameterized

from posthog.management.migration_squashing.planner import MigrationSquashPlanner
from posthog.management.migration_squashing.policy import BootstrapPolicy


def build_migration(name: str, operations: list, dependencies: list[tuple[str, str]] | None = None):
    migration = migrations.Migration(name, "posthog")
    migration.app_label = "posthog"
    migration.operations = operations
    migration.dependencies = dependencies or []
    return migration


class TestMigrationSquashPlanner:
    @parameterized.expand(
        [
            ("run_python", migrations.RunPython(lambda *_args, **_kwargs: None)),
            ("run_sql", migrations.RunSQL("SELECT 1")),
        ]
    )
    def test_opaque_operations_are_blockers(self, _name, operation):
        planner = MigrationSquashPlanner(loader=MagicMock(), app_label="posthog")
        migration = build_migration("0285_test", [operation])

        blockers = planner._find_blockers_for_migration("0285_test", migration)

        assert len(blockers) == 1
        assert blockers[0].migration == "0285_test"
        assert blockers[0].operation_index == 1
        assert blockers[0].operation_type in {"RunPython", "RunSQL"}

    def test_separate_database_and_state_with_database_operations_is_blocked(self):
        planner = MigrationSquashPlanner(loader=MagicMock(), app_label="posthog")
        operation = migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL("CREATE TABLE posthog_tmp (id int)")],
            state_operations=[],
        )
        migration = build_migration("0285_test", [operation])

        blockers = planner._find_blockers_for_migration("0285_test", migration)

        assert len(blockers) == 1
        assert blockers[0].operation_type == "RunSQL"

    def test_policy_noop_if_empty_unblocks_opaque_operation(self):
        policy = BootstrapPolicy.from_data(
            {
                "version": 1,
                "entries": [
                    {
                        "app": "posthog",
                        "migration": "0285_test",
                        "operation_index": 1,
                        "action": "noop_if_empty",
                        "tables": ["posthog_person"],
                    }
                ],
            }
        )
        planner = MigrationSquashPlanner(loader=MagicMock(), app_label="posthog", bootstrap_policy=policy)
        migration = build_migration("0285_test", [migrations.RunSQL("UPDATE posthog_person SET is_user = true")])

        blockers = planner._find_blockers_for_migration("0285_test", migration)

        assert blockers == []

    def test_rewrite_operation_for_policy_noop_if_empty_rewrites_runsql_to_guard(self):
        policy = BootstrapPolicy.from_data(
            {
                "version": 1,
                "entries": [
                    {
                        "app": "posthog",
                        "migration": "0285_test",
                        "operation_index": 1,
                        "action": "noop_if_empty",
                        "tables": ["posthog_person"],
                    }
                ],
            }
        )
        planner = MigrationSquashPlanner(loader=MagicMock(), app_label="posthog", bootstrap_policy=policy)
        state_op = migrations.AddField(
            model_name="eventdefinition",
            name="description",
            field=models.TextField(null=True),
        )
        operation = migrations.RunSQL(
            sql="UPDATE posthog_person SET is_user = true",
            state_operations=[state_op],
        )

        rewritten = planner._rewrite_operation_for_policy(
            migration_name="0285_test",
            operation_index=1,
            operation=operation,
        )

        assert rewritten.__class__.__name__ == "RunSQL"
        assert "noop_if_empty blocked" in rewritten.sql
        assert "posthog_person" in rewritten.sql
        assert rewritten.reverse_sql is migrations.RunSQL.noop
        assert rewritten.state_operations == [state_op]

    def test_separate_database_and_state_with_safe_database_operations_is_not_blocked(self):
        planner = MigrationSquashPlanner(loader=MagicMock(), app_label="posthog")
        operation = migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    "CREATE INDEX CONCURRENTLY IF NOT EXISTS posthog_idx ON posthog_eventdefinition (id)",
                    reverse_sql="DROP INDEX CONCURRENTLY IF EXISTS posthog_idx",
                )
            ],
            state_operations=[],
        )
        migration = build_migration("0285_test", [operation])

        blockers = planner._find_blockers_for_migration("0285_test", migration)

        assert blockers == []

    def test_schema_operation_has_no_blockers(self):
        planner = MigrationSquashPlanner(loader=MagicMock(), app_label="posthog")
        operation = migrations.AddField(
            model_name="eventdefinition",
            name="description",
            field=models.TextField(null=True),
        )
        migration = build_migration("0285_test", [operation])

        blockers = planner._find_blockers_for_migration("0285_test", migration)

        assert blockers == []

    def test_runsql_create_index_is_safe(self):
        planner = MigrationSquashPlanner(loader=MagicMock(), app_label="posthog")
        operation = migrations.RunSQL(
            sql="""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS posthog_idx ON posthog_eventdefinition (id)
            """,
            reverse_sql='DROP INDEX CONCURRENTLY IF EXISTS "posthog_idx"',
        )
        migration = build_migration("0285_test", [operation])

        blockers = planner._find_blockers_for_migration("0285_test", migration)

        assert blockers == []

    def test_operation_with_callable_from_migration_module_is_blocked(self):
        def validate_query_name(_value):
            return None

        validate_query_name.__module__ = "posthog.migrations.0860_add_namedquery"

        planner = MigrationSquashPlanner(loader=MagicMock(), app_label="posthog")
        operation = migrations.AddField(
            model_name="namedquery",
            name="name",
            field=models.CharField(max_length=128, validators=[validate_query_name]),
        )
        migration = build_migration("0860_add_namedquery", [operation])

        blockers = planner._find_blockers_for_migration("0860_add_namedquery", migration)

        assert len(blockers) == 1
        assert blockers[0].operation_type == "AddField"
        assert "posthog.migrations.0860_add_namedquery" in blockers[0].reason
        assert "validate_query_name" in blockers[0].reason

    def test_collect_dependencies_is_stable_and_excludes_replaced_span(self):
        loader = MagicMock()
        first = build_migration(
            "0285_add_model",
            [],
            dependencies=[("posthog", "0284_previous"), ("auth", "0011_update_proxy_permissions")],
        )
        second = build_migration(
            "0286_add_index",
            [],
            dependencies=[("posthog", "0285_add_model"), ("ee", "0037_add_conversation_approval_decisions")],
        )
        loader.disk_migrations = {
            ("posthog", "0285_add_model"): first,
            ("posthog", "0286_add_index"): second,
        }
        loader.graph = MagicMock()
        loader.graph.nodes = {
            ("posthog", "0284_previous"),
            ("auth", "0011_update_proxy_permissions"),
            ("ee", "0037_add_conversation_approval_decisions"),
            ("posthog", "0285_add_model"),
            ("posthog", "0286_add_index"),
        }
        loader.graph.root_nodes.return_value = []
        loader.graph.leaf_nodes.return_value = []

        planner = MigrationSquashPlanner(loader=loader, app_label="posthog")
        dependencies = planner._collect_dependencies([("posthog", "0285_add_model"), ("posthog", "0286_add_index")])

        assert dependencies == [
            ("auth", "0011_update_proxy_permissions"),
            ("ee", "0037_add_conversation_approval_decisions"),
            ("posthog", "0284_previous"),
        ]

    def test_collect_dependencies_resolves_replaced_dependency_nodes(self):
        loader = MagicMock()
        first = build_migration(
            "0285_add_model",
            [],
            dependencies=[("posthog", "0284_previous"), ("auth", "0011_update_proxy_permissions")],
        )
        replacement = build_migration("0001_initial_squashed_0284", [], dependencies=[])
        replacement.replaces = [("posthog", "0284_previous")]
        loader.disk_migrations = {
            ("posthog", "0285_add_model"): first,
            ("posthog", "0001_initial_squashed_0284"): replacement,
        }
        loader.graph = MagicMock()
        loader.graph.nodes = {
            ("posthog", "0001_initial_squashed_0284"),
            ("posthog", "0285_add_model"),
            ("auth", "0011_update_proxy_permissions"),
        }
        loader.graph.root_nodes.return_value = []
        loader.graph.leaf_nodes.return_value = []

        planner = MigrationSquashPlanner(loader=loader, app_label="posthog")
        dependencies = planner._collect_dependencies([("posthog", "0285_add_model")])

        assert dependencies == [
            ("auth", "0011_update_proxy_permissions"),
            ("posthog", "0001_initial_squashed_0284"),
        ]

    def test_requires_non_atomic_false_for_empty_operation_list(self):
        planner = MigrationSquashPlanner(loader=MagicMock(), app_label="posthog")

        result = planner._requires_non_atomic([])

        assert result is False

    def test_requires_non_atomic_detects_concurrent_runsql(self):
        operation = migrations.RunSQL(
            sql="CREATE INDEX CONCURRENTLY IF NOT EXISTS posthog_idx ON posthog_eventdefinition (id)",
            reverse_sql="DROP INDEX CONCURRENTLY IF EXISTS posthog_idx",
        )

        planner = MigrationSquashPlanner(loader=MagicMock(), app_label="posthog")

        result = planner._requires_non_atomic([operation])

        assert result is True

    def test_requires_non_atomic_false_for_non_concurrent_runsql(self):
        operation = migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS posthog_idx ON posthog_eventdefinition (id)",
            reverse_sql="DROP INDEX IF EXISTS posthog_idx",
        )

        planner = MigrationSquashPlanner(loader=MagicMock(), app_label="posthog")

        result = planner._requires_non_atomic([operation])

        assert result is False

    def test_inject_non_atomic_flag_adds_atomic_false_declaration(self):
        planner = MigrationSquashPlanner(loader=MagicMock(), app_label="posthog")
        rendered = "class Migration(migrations.Migration):\n\n    replaces = []\n"

        updated = planner._inject_non_atomic_flag(rendered)

        assert "class Migration(migrations.Migration):\n\n    atomic = False\n" in updated

    def test_strip_concurrently_from_sql_value(self):
        planner = MigrationSquashPlanner(loader=MagicMock(), app_label="posthog")
        sql_value = [
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_test ON posthog_eventdefinition (id)",
            ("DROP INDEX CONCURRENTLY IF EXISTS idx_test", []),
        ]

        rewritten = planner._strip_concurrently_from_sql_value(sql_value)

        assert "CONCURRENTLY" not in rewritten[0].upper()
        assert "CONCURRENTLY" not in rewritten[1][0].upper()

    def test_rewrite_operation_for_bootstrap_rewrites_runsql(self):
        planner = MigrationSquashPlanner(loader=MagicMock(), app_label="posthog")
        operation = migrations.RunSQL(
            sql="CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_test ON posthog_eventdefinition (id)",
            reverse_sql="DROP INDEX CONCURRENTLY IF EXISTS idx_test",
        )

        rewritten = planner._rewrite_operation_for_bootstrap(operation)

        assert rewritten.__class__.__name__ == "RunSQL"
        assert "CONCURRENTLY" not in rewritten.sql.upper()
        assert "CONCURRENTLY" not in rewritten.reverse_sql.upper()

    def test_prepare_operations_for_write_folds_rename_index_on_created_model(self):
        planner = MigrationSquashPlanner(loader=MagicMock(), app_label="posthog")
        create_model = migrations.CreateModel(
            name="Link",
            fields=[("id", models.AutoField(primary_key=True))],
            options={"indexes": [models.Index(fields=["id"], name="old_idx")]},
        )
        rename_index = migrations.RenameIndex(
            model_name="link",
            old_name="old_idx",
            new_name="new_idx",
        )

        prepared_operations = planner._prepare_operations_for_write(
            [create_model, rename_index],
            rewrite_concurrent_indexes=False,
        )

        assert len(prepared_operations) == 1
        assert prepared_operations[0].__class__.__name__ == "CreateModel"
        assert prepared_operations[0].options["indexes"][0].name == "new_idx"

    def test_prepare_operations_for_write_folds_rename_index_after_rename_model(self):
        planner = MigrationSquashPlanner(loader=MagicMock(), app_label="posthog")
        create_model = migrations.CreateModel(
            name="Link",
            fields=[("id", models.AutoField(primary_key=True))],
            options={"indexes": [models.Index(fields=["id"], name="old_idx")]},
        )
        rename_model = migrations.RenameModel(old_name="Link", new_name="ShortLink")
        rename_index = migrations.RenameIndex(
            model_name="shortlink",
            old_name="old_idx",
            new_name="new_idx",
        )

        prepared_operations = planner._prepare_operations_for_write(
            [create_model, rename_model, rename_index],
            rewrite_concurrent_indexes=False,
        )

        assert len(prepared_operations) == 2
        assert prepared_operations[0].__class__.__name__ == "CreateModel"
        assert prepared_operations[1].__class__.__name__ == "RenameModel"
        assert prepared_operations[0].options["indexes"][0].name == "new_idx"

    def test_prepare_operations_for_write_folds_ephemeral_create_model_lifecycle(self):
        planner = MigrationSquashPlanner(loader=MagicMock(), app_label="posthog")
        create_model = migrations.CreateModel(
            name="TeamCoreEventsConfig",
            fields=[("id", models.AutoField(primary_key=True))],
        )
        state_only_delete = migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[migrations.DeleteModel(name="TeamCoreEventsConfig")],
        )
        drop_table = migrations.RunSQL(
            sql="DROP TABLE IF EXISTS posthog_teamcoreeventsconfig;",
            reverse_sql="",
        )

        prepared_operations = planner._prepare_operations_for_write(
            [create_model, state_only_delete, drop_table],
            rewrite_concurrent_indexes=False,
        )

        assert prepared_operations == []

    def test_prepare_operations_for_write_folds_ephemeral_lifecycle_with_table_specific_db_ops(self):
        planner = MigrationSquashPlanner(loader=MagicMock(), app_label="posthog")
        create_model = migrations.CreateModel(
            name="NamedQuery",
            fields=[("id", models.AutoField(primary_key=True))],
        )
        add_constraint = migrations.AddConstraint(
            model_name="namedquery",
            constraint=models.UniqueConstraint(fields=("id",), name="uq_namedquery_id"),
        )
        delete_with_table_db_ops = migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="ALTER TABLE posthog_namedquery DROP CONSTRAINT IF EXISTS uq_namedquery_id",
                    reverse_sql="",
                )
            ],
            state_operations=[migrations.DeleteModel(name="NamedQuery")],
        )
        drop_table = migrations.RunSQL(
            sql="DROP TABLE IF EXISTS posthog_namedquery;",
            reverse_sql=(
                "CREATE TABLE IF NOT EXISTS posthog_namedquery (id integer); "
                "ALTER TABLE posthog_namedquery DROP CONSTRAINT IF EXISTS uq_namedquery_id;"
            ),
        )

        prepared_operations = planner._prepare_operations_for_write(
            [create_model, add_constraint, delete_with_table_db_ops, drop_table],
            rewrite_concurrent_indexes=False,
        )

        assert prepared_operations == []

    def test_prepare_operations_for_write_folds_fk_index_drops_for_created_model(self):
        planner = MigrationSquashPlanner(loader=MagicMock(), app_label="posthog")
        create_model = migrations.CreateModel(
            name="CohortCalculationHistory",
            fields=[
                ("id", models.AutoField(primary_key=True)),
                ("cohort", models.ForeignKey(on_delete=models.CASCADE, to="posthog.cohort")),
                ("team", models.ForeignKey(on_delete=models.CASCADE, to="posthog.team")),
            ],
            options={"db_table": "posthog_cohortcalculationhistory"},
        )
        drop_cohort_fk_index = migrations.RunSQL(
            sql="DROP INDEX CONCURRENTLY IF EXISTS posthog_cohortcalculationhistory_cohort_id_e7c02b55",
            reverse_sql=(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS posthog_cohortcalculationhistory_cohort_id_e7c02b55 "
                "ON posthog_cohortcalculationhistory (cohort_id)"
            ),
        )
        drop_team_fk_index = migrations.RunSQL(
            sql="DROP INDEX CONCURRENTLY IF EXISTS posthog_cohortcalculationhistory_team_id_beba9c96",
            reverse_sql=(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS posthog_cohortcalculationhistory_team_id_beba9c96 "
                "ON posthog_cohortcalculationhistory (team_id)"
            ),
        )

        prepared_operations = planner._prepare_operations_for_write(
            [create_model, drop_cohort_fk_index, drop_team_fk_index],
            rewrite_concurrent_indexes=False,
        )

        assert len(prepared_operations) == 1
        assert prepared_operations[0].__class__.__name__ == "CreateModel"
        field_by_name = dict(prepared_operations[0].fields)
        assert field_by_name["cohort"].db_index is False
        assert field_by_name["team"].db_index is False

    def test_prepare_operations_for_write_folds_fk_to_plain_alterfield_on_created_model(self):
        planner = MigrationSquashPlanner(loader=MagicMock(), app_label="posthog")
        create_model = migrations.CreateModel(
            name="ResourceNotebook",
            fields=[
                ("id", models.AutoField(primary_key=True)),
                ("group", models.ForeignKey(blank=True, null=True, on_delete=models.CASCADE, to="posthog.group")),
            ],
        )
        alter_group_to_integer = migrations.AlterField(
            model_name="resourcenotebook",
            name="group",
            field=models.IntegerField(blank=True, db_column="group_id", null=True),
        )

        prepared_operations = planner._prepare_operations_for_write(
            [create_model, alter_group_to_integer],
            rewrite_concurrent_indexes=False,
        )

        assert len(prepared_operations) == 1
        assert prepared_operations[0].__class__.__name__ == "CreateModel"
        field_by_name = dict(prepared_operations[0].fields)
        assert field_by_name["group"].__class__.__name__ == "IntegerField"
        assert getattr(field_by_name["group"], "remote_field", None) is None

    def test_prepare_operations_for_write_keeps_non_fk_alterfield_on_created_model(self):
        planner = MigrationSquashPlanner(loader=MagicMock(), app_label="posthog")
        create_model = migrations.CreateModel(
            name="SimpleModel",
            fields=[
                ("id", models.AutoField(primary_key=True)),
                ("name", models.CharField(max_length=64, null=True)),
            ],
        )
        alter_name = migrations.AlterField(
            model_name="simplemodel",
            name="name",
            field=models.CharField(max_length=128, null=True),
        )

        prepared_operations = planner._prepare_operations_for_write(
            [create_model, alter_name],
            rewrite_concurrent_indexes=False,
        )

        assert len(prepared_operations) == 2
        assert prepared_operations[0].__class__.__name__ == "CreateModel"
        assert prepared_operations[1].__class__.__name__ == "AlterField"

    def test_prepare_operations_for_write_normalizes_alterfield_subclasses(self):
        planner = MigrationSquashPlanner(loader=MagicMock(), app_label="posthog")

        class AlterFieldNullSafe(migrations.AlterField):
            pass

        custom_alter = AlterFieldNullSafe(
            model_name="dashboardtemplate",
            name="dashboard_description",
            field=models.CharField(blank=True, max_length=400, null=True),
        )

        prepared_operations = planner._prepare_operations_for_write(
            [custom_alter],
            rewrite_concurrent_indexes=False,
        )

        assert len(prepared_operations) == 1
        assert prepared_operations[0].__class__ is migrations.AlterField
        assert prepared_operations[0].model_name == "dashboardtemplate"
        assert prepared_operations[0].name == "dashboard_description"

    def test_prepare_operations_for_write_keeps_state_only_delete_without_drop_table(self):
        planner = MigrationSquashPlanner(loader=MagicMock(), app_label="posthog")
        create_model = migrations.CreateModel(
            name="TeamCoreEventsConfig",
            fields=[("id", models.AutoField(primary_key=True))],
        )
        state_only_delete = migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[migrations.DeleteModel(name="TeamCoreEventsConfig")],
        )

        prepared_operations = planner._prepare_operations_for_write(
            [create_model, state_only_delete],
            rewrite_concurrent_indexes=False,
        )

        assert len(prepared_operations) == 2
        assert prepared_operations[0].__class__.__name__ == "CreateModel"
        assert prepared_operations[1].__class__.__name__ == "SeparateDatabaseAndState"

    @parameterized.expand(
        [
            (
                "default_suffix",
                "0285_add_feature_flags",
                "0301_add_dashboard_indexes",
                None,
                "0285_squashed_0301_add_dashboard_indexes",
            ),
            (
                "custom_suffix",
                "0285_add_feature_flags",
                "0301_add_dashboard_indexes",
                "Core schema reset",
                "0285_squashed_0301_core_schema_reset",
            ),
        ]
    )
    def test_build_squashed_name(self, _name, start_name, end_name, suffix, expected):
        planner = MigrationSquashPlanner(loader=MagicMock(), app_label="posthog")

        result = planner.build_squashed_name(start_name, end_name, suffix)

        assert result == expected
