from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1102_organizationmembership_org_joined_idx"),
        ("social_django", "0016_alter_usersocialauth_extra_data"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserSocialAuthLoginPreference",
            fields=[
                (
                    "social_auth",
                    models.OneToOneField(
                        on_delete=models.deletion.CASCADE,
                        primary_key=True,
                        related_name="login_preference",
                        serialize=False,
                        to="social_django.usersocialauth",
                    ),
                ),
                ("login_enabled", models.BooleanField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "posthog_user_social_auth_login_preference",
            },
        ),
    ]
