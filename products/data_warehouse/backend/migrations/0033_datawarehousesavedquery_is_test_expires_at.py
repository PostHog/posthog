from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_warehouse", "0032_add_engine_to_datamodelingjob"),
    ]

    operations = [
        migrations.AddField(
            model_name="datawarehousesavedquery",
            name="is_test",
            field=models.BooleanField(
                default=False,
                help_text="Whether this view is for testing only and will auto-expire.",
            ),
        ),
        migrations.AddField(
            model_name="datawarehousesavedquery",
            name="expires_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text="When this test view should be automatically deleted.",
            ),
        ),
    ]
