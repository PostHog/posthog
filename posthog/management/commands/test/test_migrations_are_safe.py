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
