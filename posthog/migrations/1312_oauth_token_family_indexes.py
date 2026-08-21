from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    """
    Index the token family on both token tables.

    `revoke_oauth_token_family` selects a whole grant by this column on every RFC 7009 revocation,
    and DOT's refresh-token reuse protection already did the same on posthog_oauthrefreshtoken
    without an index. Built with CREATE INDEX CONCURRENTLY (SHARE UPDATE EXCLUSIVE) so token
    validation keeps running while they build.
    """

    atomic = False

    dependencies = [("posthog", "1311_oauthaccesstoken_token_family_and_more")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="oauthaccesstoken",
            index=models.Index(fields=["token_family"], name="oauthaccesstoken_family_idx"),
        ),
        SafeAddIndexConcurrently(
            model_name="oauthrefreshtoken",
            index=models.Index(fields=["token_family"], name="oauthrefreshtoken_family_idx"),
        ),
    ]
