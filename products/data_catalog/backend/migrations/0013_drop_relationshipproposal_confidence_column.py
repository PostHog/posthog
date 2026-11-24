from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("data_catalog", "0012_untrack_relationshipproposal_confidence"),
    ]

    operations = [
        migrations.RunSQL(
            sql='ALTER TABLE "data_catalog_relationshipproposal" DROP COLUMN IF EXISTS "confidence";',
            reverse_sql='ALTER TABLE "data_catalog_relationshipproposal" ADD COLUMN IF NOT EXISTS "confidence" double precision NULL;',
        ),
    ]
