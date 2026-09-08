from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderConfig:
    api_key: str = field(repr=False)
    base_url: str | None = None
