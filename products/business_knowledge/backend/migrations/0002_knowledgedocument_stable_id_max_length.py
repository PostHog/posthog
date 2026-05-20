from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("business_knowledge", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="knowledgedocument",
            name="stable_id",
            field=models.CharField(max_length=2048),
        ),
    ]
