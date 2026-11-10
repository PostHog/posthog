from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("aeo", "0009_citation_check_team_run_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="aeocitationcheck",
            name="own_domains_key",
            field=models.CharField(
                blank=True,
                help_text="Hash of the own domains that `cited`, `target_urls`, `target_best_position` and the sentiment were computed against. Null on checks recorded before it existed.",
                max_length=16,
                null=True,
            ),
        ),
    ]
