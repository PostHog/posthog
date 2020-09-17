import uuid


def generate_clickhouse_uuid() -> str:
    id = uuid.uuid4()
    return str(id)
