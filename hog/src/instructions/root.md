# How to use hog

hog is the PostHog command line.
This guide comes with the installed hog, so it matches its commands.

## Output

- hog prints JSON on stdout when an agent runs it. `-o text` prints what a person sees.
- A failure prints one JSON object on stderr: `{"error":{"code","message","hint"}}`. Branch on `code`, and follow the `hint`, which names the next step.
- `hog commands -o json` lists every command with its arguments, options and scopes. `hog <command> --help` shows one command.
- `--raw` prints a command's full result as JSON, for when the usual output leaves something out.
- `--dry-run` shows what a command would change without changing it. `HOG_DRY_RUN=1` turns it on for every command that has one, and fails the commands that would change something without one.

## Exit codes

| Code | Meaning                                       |
| ---- | --------------------------------------------- |
| 0    | Success                                       |
| 1    | The command failed, or a check found problems |
| 2    | Usage error. Fix the command and run it again |

The error `code` says why a command stopped, such as `step_up_required` when a person must add a scope.

## When a person must approve

`hog auth login`, `hog auth add` and `hog ci setup` need a person to approve in the browser.
When an agent runs them, they return at once with `"status": "pending"`, a `url`, a `code` and the `next` command.

1. Give the person the link and the code, and ask them to approve.
2. Run the `next` command, such as `hog auth login --wait`. It waits for the approval, then saves the result.
3. If it is still pending when the wait ends, run the same `--wait` command again later. The link stays the same.

## Logins and projects

- hog keeps one login per host and project. The closest `posthog.json` names the `host` and `projectId`, and that picks the login.
- `hog auth status` shows the login hog picked, why, and its scopes.
- When a login lacks a scope, the error code is `step_up_required`, and the error names the `hog auth add` command to run. Run it, have the person approve, then run the first command again.

`hog instructions auth` covers logging in, projects, scopes and CI.

## The person doesn't see hog's output

The person sees only what you tell them.
Relay what matters: links and codes to approve, what changed, and failures you can't fix.

## Other commands for agents

- PostHog product work, such as analyzing a funnel or adding a feature flag: `hog skills search <keywords>`, then `hog skills read <skill>`. `hog skills list` lists every skill.
- Installing PostHog in an app: `hog setup` shows the current step, and `hog setup next` does it.
- Connecting PostHog's MCP server to your agent: `hog mcp add`.
- Calling the PostHog API directly: `hog api search`, `info`, `schema` and `call`.
- Friction with hog, such as a confusing error or a missing option: `hog feedback "<what happened>"`.
