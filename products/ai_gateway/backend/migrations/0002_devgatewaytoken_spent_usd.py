from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai_gateway", "0001_squash_2026_11_02_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="devgatewaytoken",
            name="spent_usd",
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=12, null=True),
        ),
    ]
