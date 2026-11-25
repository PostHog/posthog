from django.db import migrations, models

# A trigger sets row_version, not save(), because QuerySet.update, bulk_update, the SET_NULL update
# of the deletion collector and raw SQL all skip save(). The trigger reads OLD.row_version and ignores
# the value in NEW, so a stale instance that saves cannot lower the version. Row locks order the
# updates, so the version rises in commit order. The repository cache columns are not in the list,
# so a cache refresh does not change the version.
SQL = """
CREATE OR REPLACE FUNCTION posthog_integration_bump_row_version() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.config, NEW.sensitive_config, NEW.errors, NEW.integration_id, NEW.kind, NEW.team_id, NEW.created_by_id)
       IS DISTINCT FROM
       (OLD.config, OLD.sensitive_config, OLD.errors, OLD.integration_id, OLD.kind, OLD.team_id, OLD.created_by_id)
    THEN
        NEW.row_version := OLD.row_version + 1;
    ELSE
        NEW.row_version := OLD.row_version;
    END IF;
    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS posthog_integration_row_version ON posthog_integration;
CREATE TRIGGER posthog_integration_row_version
    BEFORE UPDATE ON posthog_integration
    FOR EACH ROW EXECUTE FUNCTION posthog_integration_bump_row_version();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS posthog_integration_row_version ON posthog_integration;
DROP FUNCTION IF EXISTS posthog_integration_bump_row_version();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1455_user_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="integration",
            name="row_version",
            field=models.BigIntegerField(db_default=0, default=0, editable=False),
        ),
        migrations.RunSQL(sql=SQL, reverse_sql=REVERSE_SQL),
    ]
