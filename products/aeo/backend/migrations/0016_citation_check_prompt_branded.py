from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("aeo", "0015_citation_check_names_brand"),
    ]

    operations = [
        migrations.AddField(
            model_name="aeocitationcheck",
            name="prompt_branded",
            field=models.BooleanField(
                blank=True,
                help_text="The prompt as it ran names one of the own brands, matched on whole words. Kept current by the own-citation reconcile. Null on checks recorded before it existed until that reconcile fills it.",
                null=True,
            ),
        ),
    ]
