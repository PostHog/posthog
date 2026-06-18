from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True, slots=True)
class EngineConfig:
    """Deployment-level configuration the HogQL engine reads, captured as plain data.

    The third kind of compiler input, next to per-request tenant data (the
    ``DataProvider`` / ``HogQLTeamContext``) and per-query knobs
    (``HogQLQueryModifiers``): facts about the installation itself, identical for
    every query it compiles. Build it at the Django boundary with
    ``hogql_django_provider.default_engine_config`` (or by hand in tests); engine code
    depends only on this immutable data, never on ``django.conf.settings``.
    """

    # Version suffix of the user-defined functions deployed on the ClickHouse cluster
    # (e.g. "v12"), or None where the unsuffixed names from the local XML config apply.
    # Cloud deploys UDF versions side by side, so printed SQL must call the versioned name.
    udf_version: Optional[str] = None
