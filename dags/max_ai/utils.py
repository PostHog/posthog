from django.conf import settings


def compose_postgres_dump_path(project_id: int, file_name: str) -> str:
    return f"{settings.OBJECT_STORAGE_MAX_AI_EVALS_FOLDER}/models/{project_id}/{file_name}"


def compose_clickhouse_dump_path(project_id: int, file_name: str) -> str:
    return f"{settings.OBJECT_STORAGE_MAX_AI_EVALS_FOLDER}/queries/{project_id}/{file_name}"
