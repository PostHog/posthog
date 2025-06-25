import argparse
import os

import django
import IPython
import pyarrow.fs as fs
from django.conf import settings


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
    django.setup()

    parser = make_parser()
    namespace = parser.parse_args()
    start_session(
        namespace.team_id,
        namespace.batch_export_id,
    )


def make_parser():
    parser = argparse.ArgumentParser(
        prog="Batch exports debug session", description="Enter a debug session for batch exports"
    )
    parser.add_argument("-t", "--team-id", required=True, type=int)
    parser.add_argument("-b", "--batch-export-id", required=False, type=str)

    return parser


def start_session(team_id: int, batch_export_id: str):
    from posthog.batch_exports.debug.debugger import BatchExportsDebugger
    from posthog.models import BatchExport

    if settings.TEST or settings.DEBUG:
        endpoint_url = settings.BATCH_EXPORT_OBJECT_STORAGE_ENDPOINT
    else:
        endpoint_url = None

    s3fs = fs.S3FileSystem(
        access_key=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        secret_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        region=settings.BATCH_EXPORT_OBJECT_STORAGE_REGION,
        endpoint_override=endpoint_url,
    )

    if batch_export_id:
        batch_exports = [BatchExport.objects.select_related("destination").get(id=batch_export_id, team_id=team_id)]
    else:
        batch_exports = list(BatchExport.objects.select_related("destination").filter(team_id=team_id, deleted=False))

    bedbg = BatchExportsDebugger(team_id, batch_exports, s3fs)  # noqa: F841
    IPython.embed(colors="Linux")


if __name__ == "__main__":
    main()
