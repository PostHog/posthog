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


def test_new_tables_can_have_int64_ids() -> None:
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
    assert should_fail is False
