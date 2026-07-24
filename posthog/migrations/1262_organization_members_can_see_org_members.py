from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1261_alter_personalapikey_scoped_organizations_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="members_can_see_org_members",
            field=models.BooleanField(
                db_default=True,
                default=True,
                help_text="When False, members (below admin) only see themselves in the members list and only project members in access control.",
            ),
        ),
    ]
