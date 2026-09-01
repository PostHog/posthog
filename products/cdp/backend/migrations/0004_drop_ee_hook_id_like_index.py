from django.db import migrations


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("cdp", "0003_hog_function_drafts"),
    ]

    operations = [
        migrations.RunSQL(
            sql='DROP INDEX CONCURRENTLY IF EXISTS "ee_hook_id_d4e48550_like"',
            reverse_sql='CREATE INDEX CONCURRENTLY IF NOT EXISTS "ee_hook_id_d4e48550_like" ON "ee_hook" ("id" varchar_pattern_ops)',
        ),
    ]
