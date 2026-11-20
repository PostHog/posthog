from importlib import import_module

from django.db import migrations

# Rerun of 1394 (#66179): rotations between that backfill and mirror-on-rotate (#118116)
# minted tokens with no mirror row, which stop authenticating when the legacy verifiers
# go. Already-mirrored and revoked hashes are skipped, so the rerun only fills that gap.
backfill_tokens = import_module("posthog.migrations.1394_backfill_secret_tokens_to_psak").backfill_tokens


class Migration(migrations.Migration):
    dependencies = [("posthog", "1440_rename_code_review_scopes")]

    operations = [
        migrations.RunPython(backfill_tokens, migrations.RunPython.noop, elidable=True),
    ]
