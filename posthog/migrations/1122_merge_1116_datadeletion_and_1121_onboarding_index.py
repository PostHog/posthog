from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1116_datadeletionrequest_hogql_predicate"),
        ("posthog", "1121_onboarding_delegated_to_invite_index"),
    ]

    operations = []
