from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("aeo", "0020_check_unresolved_brands_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="aeobrand",
            name="mentions_resolved_before",
            field=models.DateTimeField(
                blank=True,
                help_text="The pass under way resolved every check created after this instant, and the checks at it with an id above `mentions_resolved_before_id`.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="aeobrand",
            name="mentions_resolved_before_id",
            field=models.UUIDField(
                blank=True,
                help_text="Id of the last check the pass under way resolved.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="aeobrand",
            name="mentions_resolving_key",
            field=models.CharField(
                blank=True,
                help_text="Hash of the identity a pass over the brand's history is resolving. Null when no pass is under way.",
                max_length=16,
                null=True,
            ),
        ),
    ]
