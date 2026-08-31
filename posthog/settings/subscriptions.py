"""Operational limits and kill switches for proactive prompt subscriptions."""

from posthog.settings.utils import get_from_env, get_list, str_to_bool

# The master switch is intentionally default-off. Capability switches cannot enable
# behavior by themselves; all require PULSE_PROACTIVE_ENABLED as well.
PULSE_PROACTIVE_ENABLED: bool = get_from_env("PULSE_PROACTIVE_ENABLED", False, type_cast=str_to_bool)
PULSE_DRAFT_PR_ENABLED: bool = get_from_env("PULSE_DRAFT_PR_ENABLED", False, type_cast=str_to_bool)
PULSE_EXPERIMENT_DRAFT_ENABLED: bool = get_from_env("PULSE_EXPERIMENT_DRAFT_ENABLED", False, type_cast=str_to_bool)
PULSE_PUBLIC_RESEARCH_ENABLED: bool = get_from_env("PULSE_PUBLIC_RESEARCH_ENABLED", False, type_cast=str_to_bool)
PULSE_OUTCOME_READOUT_ENABLED: bool = get_from_env("PULSE_OUTCOME_READOUT_ENABLED", False, type_cast=str_to_bool)
# Public repositories can create a draft PR only when this server-owned allowlist
# contains their normalized owner/repository name. Missing or malformed cache
# visibility metadata is denied rather than assumed private.
PULSE_PUBLIC_REPOSITORY_ALLOWLIST: list[str] = get_from_env("PULSE_PUBLIC_REPOSITORY_ALLOWLIST", [], type_cast=get_list)

PULSE_MAX_TEAM_CONCURRENT_RUNS: int = get_from_env("PULSE_MAX_TEAM_CONCURRENT_RUNS", 1, type_cast=int)
PULSE_MAX_GLOBAL_CONCURRENT_RUNS: int = get_from_env("PULSE_MAX_GLOBAL_CONCURRENT_RUNS", 10, type_cast=int)
PULSE_MAX_TEAM_DAILY_RUNS: int = get_from_env("PULSE_MAX_TEAM_DAILY_RUNS", 24, type_cast=int)
PULSE_MAX_GLOBAL_DAILY_RUNS: int = get_from_env("PULSE_MAX_GLOBAL_DAILY_RUNS", 100, type_cast=int)

PULSE_WALL_CLOCK_SECONDS: int = get_from_env("PULSE_WALL_CLOCK_SECONDS", 3600, type_cast=int)
PULSE_FINALIZATION_MARGIN_SECONDS: int = get_from_env("PULSE_FINALIZATION_MARGIN_SECONDS", 300, type_cast=int)
PULSE_MAX_ACTIONS: int = get_from_env("PULSE_MAX_ACTIONS", 3, type_cast=int)
PULSE_MAX_TOOL_CALLS: int = get_from_env("PULSE_MAX_TOOL_CALLS", 20, type_cast=int)
PULSE_MAX_PUBLIC_RESEARCH_CALLS: int = get_from_env("PULSE_MAX_PUBLIC_RESEARCH_CALLS", 3, type_cast=int)
PULSE_MAX_ACTIVE_OUTCOME_PLANS: int = get_from_env("PULSE_MAX_ACTIVE_OUTCOME_PLANS", 20, type_cast=int)
PULSE_MAX_DUE_READOUTS_PER_DELIVERY: int = get_from_env("PULSE_MAX_DUE_READOUTS_PER_DELIVERY", 3, type_cast=int)
PULSE_OUTCOME_MAX_ATTEMPTS: int = get_from_env("PULSE_OUTCOME_MAX_ATTEMPTS", 2, type_cast=int)
PULSE_OUTCOME_CLAIM_EXPIRY_SECONDS: int = get_from_env("PULSE_OUTCOME_CLAIM_EXPIRY_SECONDS", 7200, type_cast=int)
PULSE_OUTCOME_MEMORY_MAX_ROWS: int = get_from_env("PULSE_OUTCOME_MEMORY_MAX_ROWS", 50, type_cast=int)
PULSE_OUTCOME_MEMORY_MAX_BYTES: int = get_from_env("PULSE_OUTCOME_MEMORY_MAX_BYTES", 16384, type_cast=int)
# Bounds the agent model's input context window; it is not a total token-spend limit.
PULSE_MAX_AGENT_CONTEXT_TOKENS: int = get_from_env("PULSE_MAX_AGENT_CONTEXT_TOKENS", 200_000, type_cast=int)
