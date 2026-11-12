from django.db import migrations


def delete_user_interview_sharing_configurations(apps, schema_editor):
    SharingConfiguration = apps.get_model("posthog", "SharingConfiguration")
    SharingConfiguration.objects.filter(interviewee_context__isnull=False).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1434_drop_unused_activitylog_org_detail_indexes"),
    ]

    operations = [
        # Must run before 1436 untracks interviewee_context. Without that field, an interview share
        # looks like a team-wide share, and its token would authenticate team-wide endpoints.
        migrations.RunPython(delete_user_interview_sharing_configurations, migrations.RunPython.noop),
    ]
