from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("batch_exports", "0006_alter_batchexport_team_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="batchexportrun",
            name="data_interval_end",
            field=models.DateTimeField(help_text="The end of the data interval.", null=True),
        ),
    ]
