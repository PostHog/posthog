# Logins, projects and scopes

## Log in

1. Run `hog auth status`. When it shows a working login for this folder's project, you don't need to log in.
2. Ask the person whether their PostHog address starts with us.posthog.com or eu.posthog.com, unless `posthog.json` names the `host`. Self-hosted PostHog takes `--host <url>` instead of `--region`.
3. Run `hog auth login --region us` or `--region eu`. Give the person the `url` and `code` it returns. On that page they check the code, pick a project and approve. A person without an account signs up there first.
4. Run `hog auth login --wait` to save the token.

Login writes the `host` and `projectId` to the closest `posthog.json`, or creates one in this folder.
`--read-only` asks for read access only.

## Which login a command uses

- The closest `posthog.json` with `host` and `projectId` picks the login for that host and project. In a monorepo, each app can have its own `posthog.json` and login.
- `--host`, `HOG_HOST` and `HOG_PROJECT_ID` replace the values in `posthog.json`.
- When nothing names a project, hog uses the latest login to the host.
- When a project is named and hog has no login for it, the command fails with `project_mismatch`. Run `hog auth login` in that folder.
- `HOG_PERSONAL_API_KEY` wins over stored logins. It takes the project from `HOG_PROJECT_ID` or `posthog.json`.

## Missing scopes

When a login lacks a scope, the error code is `step_up_required`, and the error holds `scopes` and the `command` to run.

1. Run that command, such as `hog auth add insight:write`. It returns a link and a code, like `hog auth login`.
2. Give them to the person, then run `hog auth add --wait`.
3. Run the command that failed again.

`hog auth status` lists the scopes a login has.
A personal API key can't add scopes this way. The hint names the scopes to add to the key in PostHog.

## CI

Don't log in in CI.
From a logged-in checkout, `hog ci setup --scope <scopes>` asks an organization admin to trust the repository, so its jobs use their OIDC token.
Without `--preset`, it returns `"status": "input_required"` with the run restrictions PostHog offers, such as pushes to one branch, and starts nothing.
Ask the person which runs to trust, then run it again with those options, such as `--preset branch_push=main`.
Then it returns a link like `hog auth login`, and `hog ci setup --wait` finishes it.
Then add the `host` and `projectId` it prints to `posthog.json`, and the snippet it prints to the job.
