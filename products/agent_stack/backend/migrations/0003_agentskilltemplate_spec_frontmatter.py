from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("agent_stack", "0002_agentcustomtooltemplate_and_more"),
    ]

    operations = [
        # Tighten name / description to the Agent Skills spec caps (64 / 1024).
        # Pre-prod: existing rows are within these bounds (canonical seeds use
        # short slugs + one-line descriptions); the column-type narrowing is a
        # metadata-only change on an effectively empty table.
        migrations.AlterField(
            model_name="agentskilltemplate",
            name="name",
            field=models.CharField(max_length=64),
        ),
        migrations.AlterField(
            model_name="agentskilltemplate",
            name="description",
            field=models.CharField(blank=True, default="", max_length=1024),
        ),
        # Promote license + compatibility to first-class frontmatter columns.
        # db_default="" lands a real Postgres default so the test-env schema
        # build path (setup_test_environment, which skips migrations) and any
        # non-Django writer stay fail-open; no DROP DEFAULT follow-up.
        migrations.AddField(
            model_name="agentskilltemplate",
            name="license",
            field=models.CharField(blank=True, db_default="", default="", max_length=256),
        ),
        migrations.AddField(
            model_name="agentskilltemplate",
            name="compatibility",
            field=models.CharField(blank=True, db_default="", default="", max_length=500),
        ),
    ]
