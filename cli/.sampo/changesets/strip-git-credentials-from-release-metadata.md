---
cargo/posthog-cli: patch
---

Remove credentials from the git remote URL before storing it in release metadata. A CI checkout often writes a remote URL that embeds a token. `actions/checkout` writes the `https://x-access-token:<token>@github.com/owner/repo.git` form by default. The CLI stored that token on the release, and the error tracking API returned it to anyone with project access.

The query and the fragment are dropped too, because a token can hide in `?token=` or `#access_token=`. A remote URL is omitted entirely when a credential sits where it cannot be cleaned, such as an `@` in the path or a URL that does not parse. The repository name then falls back to the directory name.

Upgrading does not clean up releases that already hold a credential. If your CI uploaded with an affected version, rotate the token.
