from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.SeparateDatabaseAndState(
            # State: Django learns about the model. Database: adopt the existing `django_session`
            # table — create it only on a fresh DB, otherwise just add the new columns. This makes
            # the engine swap log nobody out (existing session rows are preserved as-is).
            state_operations=[
                migrations.CreateModel(
                    name="Session",
                    fields=[
                        (
                            "session_key",
                            models.CharField(
                                max_length=40, primary_key=True, serialize=False, verbose_name="session key"
                            ),
                        ),
                        ("session_data", models.TextField(verbose_name="session data")),
                        ("expire_date", models.DateTimeField(db_index=True, verbose_name="expire date")),
                        ("user_id", models.BigIntegerField(null=True)),
                        ("last_activity", models.DateTimeField(null=True)),
                        ("ip", models.GenericIPAddressField(null=True)),
                        ("short_user_agent", models.CharField(max_length=255, null=True)),
                        ("location", models.CharField(max_length=255, null=True)),
                        ("login_method", models.CharField(max_length=64, null=True)),
                    ],
                    options={"db_table": "django_session"},
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                    CREATE TABLE IF NOT EXISTS django_session (
                        session_key varchar(40) NOT NULL PRIMARY KEY,
                        session_data text NOT NULL,
                        expire_date timestamptz NOT NULL
                    );
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_indexes
                            WHERE tablename = 'django_session' AND indexdef LIKE '%(expire_date)%'
                        ) THEN
                            CREATE INDEX django_session_expire_date_idx ON django_session (expire_date);
                        END IF;
                    END
                    $$;
                    ALTER TABLE django_session ADD COLUMN IF NOT EXISTS user_id bigint NULL;
                    ALTER TABLE django_session ADD COLUMN IF NOT EXISTS last_activity timestamptz NULL;
                    ALTER TABLE django_session ADD COLUMN IF NOT EXISTS ip inet NULL;
                    ALTER TABLE django_session ADD COLUMN IF NOT EXISTS short_user_agent varchar(255) NULL;
                    ALTER TABLE django_session ADD COLUMN IF NOT EXISTS location varchar(255) NULL;
                    ALTER TABLE django_session ADD COLUMN IF NOT EXISTS login_method varchar(64) NULL;
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
