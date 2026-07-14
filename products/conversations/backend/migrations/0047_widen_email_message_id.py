from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("conversations", "0046_ticket_org_id_indexes")]

    operations = [
        migrations.AlterField(
            model_name="emailmessagemapping",
            name="message_id",
            field=models.TextField(db_index=True),
        ),
    ]
