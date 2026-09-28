"""Distributed ownership: owners.yaml matcher, schema, resolver, and CLI."""

from .census import TeamTestCensus, census, first_team_owner, runner_for_path
from .codeowners import CodeownersProjection, owner_handle, package_dirs_from, project, spellings
from .github import GitHubLookupError, GitHubOrg
from .matcher import compile_pattern, normalize_path, path_matches_pattern
from .resolver import (
    BatchOwnershipSource,
    DiskSource,
    OwnershipSource,
    OwnersResolver,
    Purpose,
    RepoRootNotFound,
    Resolution,
    TeamChannel,
    team_channel,
    teams_registry,
)
from .schema import Producer, RepoSettings, TeamEntry

__all__ = [
    "BatchOwnershipSource",
    "CodeownersProjection",
    "DiskSource",
    "GitHubLookupError",
    "GitHubOrg",
    "OwnersResolver",
    "OwnershipSource",
    "Producer",
    "Purpose",
    "RepoRootNotFound",
    "RepoSettings",
    "Resolution",
    "TeamChannel",
    "TeamEntry",
    "TeamTestCensus",
    "census",
    "compile_pattern",
    "first_team_owner",
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
