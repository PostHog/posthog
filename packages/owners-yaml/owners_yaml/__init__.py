"""Distributed ownership: owners.yaml matcher, schema, resolver, and CLI."""

from .census import TeamTestCensus, census, first_team_owner, runner_for_path
from .codeowners import CodeownersProjection, owner_handle, package_dirs_from, project, spellings
from .coverage import newly_unowned
from .github import GitHubLookupError, GitHubOrg
from .matcher import compile_pattern, normalize_path, path_matches_pattern
from .resolver import (
    Addition,
    BatchOwnershipSource,
    DiskSource,
    GitRefSource,
    OwnershipSource,
    OwnersResolver,
    PathKind,
    Purpose,
    RepoRootNotFound,
    Resolution,
    TeamChannel,
    TreeSource,
    team_channel,
    teams_registry,
)
from .schema import Producer, RepoSettings, TeamEntry


# A linked worktree gets the main clone's copy of this package, and a branch from before
# `newly_unowned` imports this name when preflight starts. Delete it when no open branch is that old.
def unowned_test_directories(*_: object) -> set[str]:
    raise NotImplementedError("unowned_test_directories is gone: merge master to check test owners")


__all__ = [
    "Addition",
    "BatchOwnershipSource",
    "CodeownersProjection",
    "DiskSource",
    "GitHubLookupError",
    "GitRefSource",
    "GitHubOrg",
    "OwnersResolver",
    "PathKind",
    "OwnershipSource",
    "Producer",
    "Purpose",
    "RepoRootNotFound",
    "RepoSettings",
    "Resolution",
    "TeamChannel",
    "TeamEntry",
    "TeamTestCensus",
    "TreeSource",
    "census",
    "compile_pattern",
    "first_team_owner",
    "newly_unowned",
    "normalize_path",
    "owner_handle",
    "package_dirs_from",
    "path_matches_pattern",
    "project",
    "runner_for_path",
    "spellings",
    "team_channel",
    "teams_registry",
]
