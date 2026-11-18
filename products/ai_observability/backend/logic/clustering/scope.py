import json
import hashlib


def scope_key(analysis_level: str, event_filters: list[dict]) -> str:
    return hashlib.sha256(json.dumps([analysis_level, event_filters], sort_keys=True).encode()).hexdigest()[:32]
