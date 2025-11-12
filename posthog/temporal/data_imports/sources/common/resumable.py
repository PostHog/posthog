import json
import dataclasses
from contextlib import contextmanager
from typing import Generic

from django.conf import settings

import orjson

from posthog.redis import get_client
from posthog.temporal.data_imports.pipelines.pipeline.typings import ResumableData, SourceInputs


class ResumableSourceManager(Generic[ResumableData]):
    _inputs: SourceInputs
    _data_class: type[ResumableData]

    def __init__(self, inputs: SourceInputs, data_class: type[ResumableData]):
        self._inputs = inputs
        self._data_class = data_class

    @contextmanager
    def _get_redis(self):
        if not settings.DATA_WAREHOUSE_REDIS_HOST or not settings.DATA_WAREHOUSE_REDIS_PORT:
            raise Exception(
                "Missing env vars for dwh row tracking: DATA_WAREHOUSE_REDIS_HOST or DATA_WAREHOUSE_REDIS_PORT"
            )

        redis = get_client(f"redis://{settings.DATA_WAREHOUSE_REDIS_HOST}:{settings.DATA_WAREHOUSE_REDIS_PORT}/")
        redis.ping()

        yield redis

    @property
    def _key(self) -> str:
        return f"posthog:data_warehouse:resumable_source:{self._inputs.team_id}:{self._inputs.job_id}"

    def _dump_json(self, data: ResumableData) -> str:
        data_dict = dataclasses.asdict(data)

        try:
            return orjson.dumps(data_dict).decode()
        except TypeError:
            try:
                return json.dumps(data_dict)
            except Exception:
                return str(data_dict)

    def _load_json(self, data: str) -> ResumableData:
        try:
            parsed_data = orjson.loads(data)
        except orjson.JSONDecodeError:
            try:
                parsed_data = json.loads(data)
            except Exception as e:
                raise ValueError(f"Failed to load resumable data: {data}") from e

        return self._data_class(**parsed_data)

    def save_state(self, data: ResumableData) -> None:
        with self._get_redis() as redis:
            json_data = self._dump_json(data)
            redis.set(self._key, json_data, ex=60 * 60 * 24)  # 24 hours expiration

    def can_resume(self) -> bool:
        with self._get_redis() as redis:
            return redis.exists(self._key) == 1

    def load_state(self) -> ResumableData | None:
        with self._get_redis() as redis:
            data = redis.get(self._key)
            if not data:
                return None

            return self._load_json(data)
