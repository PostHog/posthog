import argparse
import os

import django
import IPython


def main():
    """Entrypoint to start a debug session."""
    _ = os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
    django.setup()

    parser = make_parser()
    namespace = parser.parse_args()
    start_session(
        namespace.team_id,
        namespace.batch_export_id,
    )


def make_parser():
    """Parse arguments for debug session CLI."""
    parser = argparse.ArgumentParser(
        prog="Batch exports debug session", description="Enter a debug session for batch exports"
    )
    _ = parser.add_argument("team_id", type=int, help="The ID of the team we are debugging.")
    _ = parser.add_argument(
        "-b",
        "--batch-export-id",
        required=False,
        type=str,
        help="Optionally, narrow down the search to a batch export if you already have its ID.",
    )

    return parser


def start_session(team_id: int, batch_export_id: str | None = None):
    """Start a debugging session with a debugger in an IPython shell."""
    from posthog.batch_exports.debug.debugger import BatchExportsDebugger
    from posthog.models import BatchExport

    initial_batch_export: BatchExport | None = None
    if batch_export_id:
        initial_batch_export = BatchExport.objects.select_related("destination").get(
            id=batch_export_id, team_id=team_id
        )

    bedbg = BatchExportsDebugger(team_id, initial_batch_export=initial_batch_export)  # noqa: F841
    IPython.embed(colors="Linux")


if __name__ == "__main__":
    main()
