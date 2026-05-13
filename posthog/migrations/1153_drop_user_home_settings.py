from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1152_fix_device_bucketing_persist_across_auth"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="userhomesettings",
            name="posthog_unique_user_home_settings",
        ),
        migrations.DeleteModel(
            name="UserHomeSettings",
        ),
    ]
