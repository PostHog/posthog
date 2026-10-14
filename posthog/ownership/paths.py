"""Which team owns each path of a repository, resolved from the repository's own ownership files.

The answer comes from the repository as it stands, not from anything PostHog stores, so a caller
needs no team and gets whoever owes the work now.
"""

from collections.abc import Mapping, Sequence

import structlog
from owners_yaml import OwnersResolver
from owners_yaml.resolver import teams_registry
from owners_yaml.schema import TeamEntry
from pydantic.dataclasses import dataclass

from posthog.ownership.repo_files import (
    ROOT_OWNERS_FILE,
    GitHubRepoFiles,
    NoRootOwnersFile,
    OwnershipUnavailable,
    RepoFiles,
)

logger = structlog.get_logger(__name__)

# The first-class team every unattributed path aggregates under, on every surface that reads this.
UNOWNED_TEAM = "unowned"


@dataclass(frozen=True)
class PathOwnership:
    """Which team owns each repository path, plus the repo's Slack registry from the root ``owners.yaml``.
    The registry rides along because the caller that asks who owns a path usually has to reach that
    team next, and the root file answers both questions in one read.

    ``resolved`` is false when the ownership files could not be read; every path is then
    ``UNOWNED_TEAM`` and the registry is empty. A caller that says so beats one that reads the blind
    answer as "nobody owns this"."""

    team_by_path: Mapping[str, str]
    registry: Mapping[str, TeamEntry]
    resolved: bool


def _team(owners: list[str] | None) -> str:
    """An '@handle' owner is a person, and every surface downstream keys on a team slug."""
    return next((owner for owner in owners or [] if not owner.startswith("@")), UNOWNED_TEAM)


def own_paths(files: RepoFiles, root: str, paths: list[str]) -> PathOwnership:
    owners = OwnersResolver(source=files).map(paths)
    return PathOwnership(
        team_by_path={path: _team(owners[path].owners) for path in paths},
        registry=teams_registry(root),
        resolved=True,
    )


def read_root(repository: str, files: RepoFiles) -> str:
    root = files.read(ROOT_OWNERS_FILE)
    if root is None:
        raise NoRootOwnersFile(f"{repository} has no root {ROOT_OWNERS_FILE}")
    return root


def resolve_path_owners(repository: str, paths: Sequence[str], files: RepoFiles | None = None) -> PathOwnership:
    """Name the team that owns each repository path, and return the repo's Slack registry. Paths must
    be repo-relative: unlike reported test paths, they get no candidate-path search."""
    reader = files if files is not None else GitHubRepoFiles(repository)
    try:
        return own_paths(reader, read_root(repository, reader), list(dict.fromkeys(paths)))
    except NoRootOwnersFile:
        # Most repositories declare no owners.yaml, so this is no error for a caller to act on.
        logger.info("repo_path_ownership_no_root_file", repository=repository)
        return PathOwnership(team_by_path=dict.fromkeys(paths, UNOWNED_TEAM), registry={}, resolved=False)
    except OwnershipUnavailable:
        logger.exception("repo_path_ownership_unavailable", repository=repository)
        return PathOwnership(team_by_path=dict.fromkeys(paths, UNOWNED_TEAM), registry={}, resolved=False)
