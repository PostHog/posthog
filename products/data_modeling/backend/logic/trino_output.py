from uuid import UUID

from django.conf import settings


def trino_output_folder(*, organization_id: str, team_id: int, saved_query_id: UUID, run_id: str) -> str | None:
    """The S3 folder one Trino run writes its Parquet copy to, or None when the copy is turned off.

    Each run gets a folder of its own, so a read never meets the files of a run that is still writing.
    """
    base = settings.DATA_MODELING_TRINO_OUTPUT_BUCKET_URL.rstrip("/")
    if not base:
        return None
    return f"{base}/org_{organization_id}/team_{team_id}/{saved_query_id.hex}/{run_id}/"
