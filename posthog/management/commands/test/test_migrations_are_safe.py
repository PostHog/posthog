import re

from posthog.management.commands.test_migrations_are_safe import validate_migration_sql


def test_new_tables_must_not_have_int_32_ids() -> None:
    sql_for_model_with_int32 = """
BEGIN;
--
-- Create model StrawMan
--
CREATE TABLE "posthog_strawman" ("id" serial NOT NULL PRIMARY KEY, "name" varchar(400) NULL);
COMMIT;
BEGIN;
--
-- Create model StrawMan
--
CREATE TABLE "posthog_strawman" ("id" serial NOT NULL PRIMARY KEY, "name" varchar(400) NULL);
COMMIT;
"""
    should_fail = validate_migration_sql(sql_for_model_with_int32)
    assert should_fail is True


def test_new_tables_must_not_have_int64_ids() -> None:
    sql_for_model_with_int64 = """
BEGIN;
--
-- Create model StrawMan
--
CREATE TABLE "posthog_strawman" ("id" bigserial NOT NULL PRIMARY KEY, "name" varchar(400) NULL);
COMMIT;
BEGIN;
--
-- Create model StrawMan
--
CREATE TABLE "posthog_strawman" ("id" bigserial NOT NULL PRIMARY KEY, "name" varchar(400) NULL);
COMMIT;
    """
    should_fail = validate_migration_sql(sql_for_model_with_int64)
    assert should_fail is True


def test_new_tables_can_have_uuid_ids() -> None:
    sql_for_model_with_uuid = """
BEGIN;
--
-- Create model StrawMan
--
CREATE TABLE "posthog_strawman" ("id" uuid NOT NULL PRIMARY KEY, "name" varchar(400) NULL);
COMMIT;
BEGIN;
--
-- Create model StrawMan
--
CREATE TABLE "posthog_strawman" ("id" uuid NOT NULL PRIMARY KEY, "name" varchar(400) NULL);
COMMIT;
    """
    should_fail = validate_migration_sql(sql_for_model_with_uuid)
    assert should_fail is False


def test_unique_indexes_can_apply_only_to_not_null_values() -> None:
    sql_for_unique_index_with_where = """
BEGIN;
CREATE UNIQUE INDEX CONCURRENTLY team_secret_api_token_unique_idx ON posthog_team (secret_api_token) WHERE secret_api_token IS NOT NULL;
COMMIT;
    """
    should_fail = validate_migration_sql(sql_for_unique_index_with_where)
    assert should_fail is False


def test_add_column_with_constant_string_default_is_safe() -> None:
    sql_with_constant_string_default = """
BEGIN;
--
-- Add field default_experiment_stats_method to organization
--
ALTER TABLE "posthog_organization" ADD COLUMN "default_experiment_stats_method" varchar(20) DEFAULT 'bayesian' NOT NULL;
ALTER TABLE "posthog_organization" ALTER COLUMN "default_experiment_stats_method" DROP DEFAULT;
COMMIT;
    """
    should_fail = validate_migration_sql(sql_with_constant_string_default)
    assert should_fail is False


def test_add_column_with_constant_number_default_is_safe() -> None:
    sql_with_constant_number_default = """
BEGIN;
ALTER TABLE "posthog_organization" ADD COLUMN "max_items" integer DEFAULT 100 NOT NULL;
COMMIT;
    """
    should_fail = validate_migration_sql(sql_with_constant_number_default)
    assert should_fail is False


def test_add_column_with_constant_boolean_default_is_safe() -> None:
    sql_with_constant_boolean_default = """
BEGIN;
ALTER TABLE "posthog_organization" ADD COLUMN "is_enabled" boolean DEFAULT TRUE NOT NULL;
COMMIT;
    """
    should_fail = validate_migration_sql(sql_with_constant_boolean_default)
    assert should_fail is False


def test_add_column_with_now_function_default_is_safe() -> None:
    sql_with_now_default = """
BEGIN;
ALTER TABLE "posthog_organization" ADD COLUMN "created_at" timestamp DEFAULT NOW() NOT NULL;
COMMIT;
    """
    should_fail = validate_migration_sql(sql_with_now_default)
    assert should_fail is False


def test_add_column_with_volatile_function_default_is_unsafe() -> None:
    sql_with_volatile_default = """
BEGIN;
ALTER TABLE "posthog_organization" ADD COLUMN "expires_at" timestamp DEFAULT NOW() + INTERVAL '1 day' NOT NULL;
COMMIT;
    """
    should_fail = validate_migration_sql(sql_with_volatile_default)
    assert should_fail is True


def test_add_column_with_no_default_not_null_is_unsafe() -> None:
    sql_with_no_default = """
BEGIN;
ALTER TABLE "posthog_organization" ADD COLUMN "required_field" varchar(20) NOT NULL;
COMMIT;
    """
    should_fail = validate_migration_sql(sql_with_no_default)
    assert should_fail is True


def test_add_column_with_nullable_field_is_safe() -> None:
    sql_with_nullable_field = """
BEGIN;
ALTER TABLE "posthog_organization" ADD COLUMN "optional_field" varchar(20) NULL;
COMMIT;
    """
    should_fail = validate_migration_sql(sql_with_nullable_field)
    assert should_fail is False


def test_add_column_with_random_function_default_is_unsafe() -> None:
    sql_with_random_default = """
BEGIN;
ALTER TABLE "posthog_organization" ADD COLUMN "random_value" float DEFAULT random() NOT NULL;
COMMIT;
    """
    should_fail = validate_migration_sql(sql_with_random_default)
    assert should_fail is True


def test_migration_path_regex_handles_products_structure() -> None:
    products_match = re.findall(
        r"products/([a-z_]+)/backend/migrations/([a-zA-Z_0-9]+)\.py",
        "products/tasks/backend/migrations/0006_remove_workflowstage_agent.py",
    )
    assert products_match == [("tasks", "0006_remove_workflowstage_agent")]

    products_match = re.findall(
        r"products/([a-z_]+)/backend/migrations/([a-zA-Z_0-9]+)\.py",
        "products/early_access_features/backend/migrations/0001_initial.py",
    )
    assert products_match == [("early_access_features", "0001_initial")]

    products_match = re.findall(
        r"products/([a-z_]+)/backend/migrations/([a-zA-Z_0-9]+)\.py", "posthog/migrations/0770_something.py"
    )
    assert products_match == []

    posthog_match = re.findall(r"([a-z]+)\/migrations\/([a-zA-Z_0-9]+)\.py", "posthog/migrations/0770_something.py")
    assert posthog_match == [("posthog", "0770_something")]
