from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    """
    Index the token family on the access token table, matching the one
    1312_oauthrefreshtoken_oauthrefreshtoken_family_idx added on the refresh token table.
    `revoke_oauth_grant_session` selects a whole grant by this column on every RFC 7009 revocation.

    Built with CREATE INDEX CONCURRENTLY (SHARE UPDATE EXCLUSIVE) so token validation keeps running
    while it builds.
    """

    atomic = False

    dependencies = [("posthog", "1314_oauthaccesstoken_token_family")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="oauthaccesstoken",
            index=models.Index(fields=["token_family"], name="oauthaccesstoken_family_idx"),
        ),
    ]
