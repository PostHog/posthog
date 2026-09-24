# Ownership

Who owns a path in a code repository.

The answer comes from the repository's own `owners.yaml` files, parsed by the `owners_yaml` package.
This module adds the part `owners_yaml` does not have: a source that reads those files over the network.
A server process has no checkout of the repository it reports on.

Both readers read the default branch, never the head of a pull request.
A pull request can edit ownership files, so a read at its head would let it name its own owners and route its own approval.

## Layout

- `repo_files.py`: `GitHubRepoFiles`, the anonymous source, plus the `RepoFiles` protocol and the `OwnershipUnavailable` errors.
- `github_files.py`: `GitHubFilesFetcher`, the authenticated reader, `AuthenticatedRepoFiles`, the source built on it, and `fetcher_for_team`.
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

The whole resolution has a time budget, so a stalled host releases the worker instead of holding it.
A file above the size limit is refused.
All GitHub traffic goes through the GitHub egress transport, and every caller names its lane: `NORMAL` where a person waits for the page, `BATCH` for scheduled work.

## How the files are read

There are two readers, and a caller picks one by what credential it holds.

`AuthenticatedRepoFiles` reads through the GitHub GraphQL API with a credential.
It resolves the default branch's head commit first, then reads the batch's files at that commit, about a hundred files per request, with the chunks in parallel.
GitHub charges one rate-limit point per request whatever the number of aliased files in it, and it answers a few hundred files with a 502, which is what sets the chunk size.
A file the commit does not hold comes back as absent.
This reader answers for a private repository.

`GitHubRepoFiles` reads `raw.githubusercontent.com` anonymously, one request per file, and caches for six hours with jitter.
The raw host serves public repositories only, so this reader is the fallback for a repository no credential covers.
It reads at the ref `HEAD` rather than at a commit, because it has no credential to ask the API which commit the default branch points at.

The authenticated reader caches per commit.
The content at a commit never changes, so a blob is held for a day; the head lookup is held for about two minutes, and that is the whole staleness window of an ownership change.
A busy repository moves its head between most reads, and each new commit starts with no entries.
So a reader that sees a new head records the head it replaced, and the first miss at the new commit asks GitHub's compare API which paths changed between the two.
Entries for the other paths are copied from the previous commit, and only the changed paths are read again.
The copy happens only when the compare proves it: the new head descends from the old one, and GitHub listed every changed file, renames included.
Any other answer, or a failed compare, falls back to a full read.
The cache key names the credential's audience, an installation or a digest of a token, because a private repository one installation can read is not readable by the next caller that names the same repository.
A token never reaches a cache key or a log line.
Pass `fresh_head=True` when the run derives a decision it never stores and so cannot correct later, such as digest routing, and the reader asks GitHub for the head instead of reading that shared entry.

## How a caller gets a source

- The caller holds a GitHub integration: `AuthenticatedRepoFiles(repository, GitHubFilesFetcher.from_integration(integration, priority=...))`.
- The caller holds a bare token, such as a warehouse source's personal access token or a product's own installation token: `GitHubFilesFetcher.from_token(token, installation_id=..., priority=...)`.
- The caller holds only a team: `fetcher_for_team(team_id, repository, priority=...)`, which finds the team's GitHub integration whose installation covers the repository and falls back to the anonymous reader.

`resolve_path_owners` still defaults to the anonymous reader, so a caller that passes no source keeps working.
