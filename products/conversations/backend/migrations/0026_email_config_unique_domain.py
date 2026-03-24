from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0025_email_channel"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="teamconversationsemailconfig",
            constraint=models.UniqueConstraint(fields=["domain"], name="unique_email_domain"),
        ),
    ]
