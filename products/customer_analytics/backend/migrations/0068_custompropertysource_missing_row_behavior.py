from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("customer_analytics", "0067_membership_cleanup")]

    operations = [
        migrations.AddField(
            model_name="custompropertysource",
            name="missing_row_behavior",
            field=models.CharField(
                choices=[("keep", "keep"), ("remove", "remove")],
                db_default="keep",
                default="keep",
                help_text="What happens to mapped person properties when the key leaves a complete table read.",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="custompropertysyncrun",
            name="removed",
            field=models.PositiveIntegerField(db_default=0, default=0),
        ),
    ]
