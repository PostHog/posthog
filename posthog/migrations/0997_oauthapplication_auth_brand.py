from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0996_oauthapplication_is_first_party"),
    ]

    operations = [
        migrations.AddField(
            model_name="oauthapplication",
            name="auth_brand",
            field=models.CharField(
                choices=[("posthog", "posthog"), ("twig", "twig")],
                default="posthog",
                help_text="Branding to use on authentication pages",
                max_length=32,
            ),
        ),
    ]
