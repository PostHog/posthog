from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Add the authorization grant an access token belongs to, so an RFC 7009 revocation can be scoped
    to that grant instead of to every token the user holds for the application.

    Nullable with no default, so this is a catalog-only ADD COLUMN with no table rewrite. The index
    on this column is built concurrently in the next migration, because every OAuth-authenticated
    request reads this table and a blocking index build would stall them.
    """

    dependencies = [
        ("posthog", "1313_healthissue_snoozed_until"),
    ]

    operations = [
        migrations.AddField(
            model_name="oauthaccesstoken",
            name="token_family",
            field=models.UUIDField(blank=True, editable=False, null=True),
        ),
    ]
