# Do not import Django here.
from pydantic import BaseModel


class EvalsDockerImageConfig(BaseModel):
    class Config:
        extra = "allow"

    database_url: str
    bucket_name: str
    endpoint_url: str
    file_key: str
