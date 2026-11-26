from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0063_node_subscription"),
    ]

    operations = [
        migrations.AddField(
            model_name="datamodelingjob",
            name="read_scopes",
            field=models.JSONField(
                blank=True,
                help_text="Access-controlled resources whose tables this run's query read. Null means not recorded.",
                null=True,
            ),
        ),
    ]
