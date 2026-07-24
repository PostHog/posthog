from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderConfig:
    api_key: str
    base_url: str | None = None
