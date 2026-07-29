from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("posthog", "1266_comment_convo_content_trgm")]

    operations = [
        migrations.AddField(
            model_name="oauthapplication",
            name="provisioning_approved",
            field=models.BooleanField(
                default=False,
                help_text="Admin approval for provisioning access. Must be explicitly set by an admin before this app can use provisioning endpoints.",
            ),
        ),
    ]
