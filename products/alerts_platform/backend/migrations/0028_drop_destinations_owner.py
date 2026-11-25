from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("alerts_platform", "0027_untrack_destinations_owner"),
    ]

    operations = [
        # Phase 2 of retiring the column: 0027 took it out of model state and has been deployed,
        # so no running pod names it. The reverse re-adds it with its old type and database
        # default, which refills every row with "source" rather than the values the drop discarded.
        migrations.RunSQL(
            sql='ALTER TABLE "alerts_platformalertconfiguration" DROP COLUMN IF EXISTS "destinations_owner";',
            reverse_sql=(
                'ALTER TABLE "alerts_platformalertconfiguration" '
                "ADD COLUMN IF NOT EXISTS \"destinations_owner\" varchar(16) DEFAULT 'source' NOT NULL;"
            ),
        ),
    ]
