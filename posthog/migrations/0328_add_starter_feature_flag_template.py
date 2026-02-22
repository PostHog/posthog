from django.db import migrations

import posthog.helpers.migration_seeds


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0327_alter_earlyaccessfeature_stage"),
    ]

    operations = [
        migrations.RunPython(
            posthog.helpers.migration_seeds.create_starter_feature_flag_template,
            reverse_code=migrations.RunPython.noop,
        )
    ]
