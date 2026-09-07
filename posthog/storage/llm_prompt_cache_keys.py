from posthog.dataclasses import frozen
from posthog.models.team.team import Team
from posthog.storage.hypercache import KeyType


def _prompt_cache_key_prefix(team: Team | str | int, prompt_name: str) -> str:
    team_identifier = team.id if isinstance(team, Team) else team
    return f"{team_identifier}:{prompt_name}"


def prompt_latest_cache_key(team: Team | str | int, prompt_name: str) -> str:
    return f"{_prompt_cache_key_prefix(team, prompt_name)}:latest"


def prompt_version_cache_key(team: Team | str | int, prompt_name: str, version: int) -> str:
    return f"{_prompt_cache_key_prefix(team, prompt_name)}:v:{version}"


def prompt_label_cache_key(team: Team | str | int, prompt_name: str, label_name: str) -> str:
    # Prompt names and label names both forbid ":", so splitting on it stays unambiguous.
    return f"{_prompt_cache_key_prefix(team, prompt_name)}:label:{label_name}"


@frozen
class ParsedPromptCacheKey:
    team_id: int
    prompt_name: str
    version: int | None = None
    label: str | None = None


def parse_prompt_cache_key(cache_key: KeyType) -> ParsedPromptCacheKey | None:
    """Parse a prompt cache key into a ParsedPromptCacheKey.

    Latest keys have version=None and label=None; version and label keys carry
    exactly one of the two.
    """
    if not isinstance(cache_key, str):
        return None

    parts = cache_key.split(":")
    if len(parts) not in (3, 4):
        return None

    team_id_str, prompt_name = parts[0], parts[1]
    if not prompt_name:
        return None

    try:
        team_id = int(team_id_str)
    except ValueError:
        return None

    if len(parts) == 3 and parts[2] == "latest":
        return ParsedPromptCacheKey(team_id=team_id, prompt_name=prompt_name)

    if len(parts) == 4 and parts[2] == "v":
        try:
            version = int(parts[3])
        except ValueError:
            return None
        if version < 1:
            return None
        return ParsedPromptCacheKey(team_id=team_id, prompt_name=prompt_name, version=version)

    if len(parts) == 4 and parts[2] == "label" and parts[3]:
        return ParsedPromptCacheKey(team_id=team_id, prompt_name=prompt_name, label=parts[3])

    return None
