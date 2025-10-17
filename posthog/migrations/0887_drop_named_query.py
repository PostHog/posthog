from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0886_fake_social_django_jsonfield_migrations"),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS posthog_namedquery;",
            reverse_sql="""
                CREATE TABLE IF NOT EXISTS posthog_namedquery (
                    id UUID PRIMARY KEY,
                    team_id INTEGER NOT NULL,
                    name VARCHAR(128) NOT NULL
                );
                ALTER TABLE posthog_namedquery ADD CONSTRAINT unique_team_named_query_name UNIQUE (team_id, name);
            """,
        ),
    ]
