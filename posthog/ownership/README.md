# Ownership

Who owns a path in a code repository.

The answer comes from the repository's own `owners.yaml` files, parsed by the `owners_yaml` package.
This module adds the part `owners_yaml` does not have: a source that reads those files over the network.
A server process has no checkout of the repository it reports on.

## Layout

- `repo_files.py`: `GitHubRepoFiles`, the network source, plus the `RepoFiles` protocol and the `OwnershipUnavailable` errors.
- `paths.py`: `resolve_path_owners`, the entry point, and the `PathOwnership` contract it returns.

## Callers

- Engineering analytics: the team that owns a quarantined test.
- Visual review: the team that owns a Storybook snapshot, and the debt digest that splits per team.
- Signals: the team that owns the files a pull request changes.

## Behavior

Reads are fail-closed.
One unreadable file makes every other answer in the batch suspect, so the whole batch fails together.
`PathOwnership.resolved` is then false, every path is `UNOWNED_TEAM`, and the registry is empty.
A repository with no root `owners.yaml` resolves to the same answer, because a private or renamed repository answers 404 to every path and cannot be told apart from one that declares nothing.

Files are fetched from `raw.githubusercontent.com` through the GitHub egress transport, in parallel, and cached in Redis for six hours with jitter.
The whole resolution has a time budget, so a stalled host releases the worker instead of holding it.
A file above the size limit is refused.

The raw host serves public repositories only.
An authenticated batch fetcher is planned, which will let this read private repositories.
