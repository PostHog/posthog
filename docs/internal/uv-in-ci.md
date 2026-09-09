# uv in CI

Use `./.github/actions/setup-uv` for GitHub Actions and its `./.depot/actions/setup-uv` mirror for Depot CI.
The composite pins both the upstream action commit and the uv release.
It does not read `pyproject.toml`: `tool.uv.required-version` remains the minimum supported developer version, not CI's selected release.

The defaults enable the dependency cache, key it against the root `uv.lock`, and save only on `master`.
Use `enable-cache: false` for tool-only jobs that do not install the project.
Override `cache-dependency-glob` when a job installs a different project, and `save-cache: false` when a master job must remain read-only.
The `cache-hit` output remains available to callers.

## Updating uv

Update the exact `version:` in the GitHub composite and its Depot mirror, plus the direct-install exceptions below.
Keep container and sandbox installer pins aligned, and regenerate the Flox lock through Flox.
Run `python3 -S bin/check_uv_python_compatibility.py` to check CI pin agreement, the developer minimum, Python download availability, and Flox alignment.
Python CI watches both composites and Depot workflows so mirror-only edits run the validator.

## Checkouts that cannot use the local action

A local action must exist in the checked-out revision.
A workflow can run from a merge revision while a later checkout selects an older PR head, PR base, or user-supplied revision.
Those trees may not contain the new composite.
Do not change what a publishing, testing, or reporting job checks out just to make its setup action available.

These jobs keep exact direct pins until their revision contract guarantees the composite exists:

- Package publishing jobs that check out a PR head to commit version and lockfile updates.
- Django, OpenAPI, E2E, and AI evaluation jobs that explicitly select the PR head.
- Timing reporters that deliberately select the PR head or base.
- Golden snapshot rendering, which accepts a user-supplied source revision.
- Conflict resolution, which must operate on conflicting branches before they can incorporate master.

Existing pnpm composites do not establish that a newly added uv composite exists in those revisions.
The compatibility check includes direct installs so exceptions cannot silently select a different uv release.
A sparse checkout that uses the composite must include its directory.

## GitHub API rate-limit history

[#48557](https://github.com/PostHog/posthog/pull/48557) removed workflow version pins in favor of `pyproject.toml`.
With a range rather than an exact version, setup-uv v7.3.0 resolved releases through the authenticated GitHub REST API.
Its [resolver](https://github.com/astral-sh/setup-uv/blob/eac588ad8def6316056a12d4907a9d4d84ff7a3b/src/download/download-version.ts) paginates `repos.listReleases` for ranges, or requests the latest release for a minimum-only constraint.
Repeating that work across concurrent jobs exhausted the token budget and caused unrelated API consumers to fail.
[#48610](https://github.com/PostHog/posthog/pull/48610) restored exact pins; [#48613](https://github.com/PostHog/posthog/pull/48613) added enforcement.

The pinned setup-uv v7.6.0 follows a different path:

1. An explicit exact version returns from `resolveVersion` without listing releases.
2. A tool-cache hit requires no download.
3. A cold install fetches `https://raw.githubusercontent.com/astral-sh/versions/main/v1/uv.ndjson` without an authorization header.
4. The binary downloads from Astral's mirror, with a fallback to the direct GitHub Releases artifact URL.
   Neither is the releases REST API.

See the pinned [resolver and download code](https://github.com/astral-sh/setup-uv/blob/37802adc94f370d6bfd71619e3f0bf239e1f3b78/src/download/download-version.ts) and [manifest client](https://github.com/astral-sh/setup-uv/blob/37802adc94f370d6bfd71619e3f0bf239e1f3b78/src/download/versions-client.ts).
Ranges also use that static manifest in v7.6.0, but exact pins still prevent an upstream release from changing CI without a repository change.

This behavior is inside the action and applies to both GitHub Actions and Depot CI.
Depot runners executing GitHub Actions are not the same as Depot CI: verify the latter through a `depot.dev` run, not merely a runner name.
Recheck the download and fallback paths whenever upgrading the upstream action.
