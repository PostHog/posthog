import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1257_datadeletionrequest_approved_automatically_and_more"),
        ("user_interviews", "0008_userinterview_user_interview_classif_gin"),
    ]

    operations = [
        migrations.AddField(
            model_name="sharingconfiguration",
            name="user_interview_topic",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="sharing_configurations",
                to="user_interviews.userinterviewtopic",
            ),
        ),
    ]
