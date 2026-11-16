from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("data_catalog", "0009_metric_embedding"),
    ]

    operations = [
        migrations.RunSQL(
            sql='ALTER TABLE "data_catalog_metric" DROP COLUMN IF EXISTS "confidence";',
            reverse_sql='ALTER TABLE "data_catalog_metric" ADD COLUMN IF NOT EXISTS "confidence" double precision NULL;',
        ),
    ]
