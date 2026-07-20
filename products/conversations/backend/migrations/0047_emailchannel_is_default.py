from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0046_ticket_org_id_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="emailchannel",
            name="is_default",
            field=models.BooleanField(default=False),
        ),
    ]
