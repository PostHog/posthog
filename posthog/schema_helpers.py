from pydantic import BaseModel


def to_json(query: BaseModel) -> str:
    return query.model_dump_json(exclude_defaults=True, exclude_none=True)
