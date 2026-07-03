from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0043_zendesk_ticket_uniq"),
    ]

    operations = [
        # Dropped: imported tickets no longer resolve a distinct_id from a person's
        # `properties.email` (attacker-settable analytics data → identity poisoning). The Zendesk
        # requester email is used verbatim as the access identity, so this resolution cache is gone.
        migrations.RemoveField(
            model_name="zendeskimportjob",
            name="email_distinct_id_cache",
        ),
    ]
