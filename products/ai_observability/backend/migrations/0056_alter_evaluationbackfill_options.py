from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0055_validate_offline_evaluation_ownership"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="evaluationbackfill",
            options={"ordering": ["-created_at", "id"]},
        ),
    ]
