# Refusals

A refusal is the failure mode of the SDK and the CLI. It fires before anything reaches PostHog, so you fix the file rather than a half-written workflow.

## The contract

Every refusal is a `WorkflowError` with four fields:

| Field     | Holds                                                                       |
| --------- | --------------------------------------------------------------------------- |
| `status`  | A stable code to branch on, for example `missing_secret`. Match it exactly. |
| `message` | What happened, in one sentence.                                             |
| `why`     | Why the SDK refuses rather than accepts.                                    |
| `fix`     | The next action that makes it pass.                                         |

The CLI prints the four fields as four labeled lines on stderr and exits 1. `error.print()` gives the same four lines in code. PostHog refuses a write with the same four fields, so one handler covers both. A resolved secret value that PostHog echoes back is replaced with `[redacted]` before it is printed.

Read `status` first, then do what `fix` says. The tables below list every literal `status: '...'` string the sources define.

## Command line

| Status                 | Meaning                                                                   |
| ---------------------- | ------------------------------------------------------------------------- |
| `unknown_command`      | The first argument is not `init`, `check` or `push`.                      |
| `missing_file`         | The command was given no file. Every command takes one path.              |
| `too_many_files`       | More than one file. Run the command once per file.                        |
| `unknown_option`       | An option other than `--force`, `--allow-move`, `--project` and `--host`. |
| `missing_option_value` | `--project` or `--host` without a value.                                  |
| `invalid_project`      | `--project` is not an ASCII decimal number.                               |

## `init`

| Status                  | Meaning                                                                                                                                                 |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `unnamed_workflow_file` | The file name holds no letters or digits, so no key or name can be taken from it.                                                                       |
| `file_exists`           | The file exists. `init` never overwrites.                                                                                                               |
| `draft`                 | Not a refusal. `init` writes `status: 'draft'` into the starter, which makes the file own the status. Remove the field unless code must own the status. |

## Loading the file

| Status                   | Meaning                                                                                       |
| ------------------------ | --------------------------------------------------------------------------------------------- |
| `load_failed`            | The file threw while it evaluated. `why` carries the error. Run your own `tsc` over the file. |
| `not_a_workflow`         | The file exports a step or a path that was never wrapped in `workflow()`.                     |
| `no_workflows`           | No export is a workflow. An unexported `const` is invisible.                                  |
| `placeholder_key`        | The key still starts with `replace-me`. Give the workflow its own key.                        |
| `duplicate_workflow_key` | Two exported workflows share one key.                                                         |

## Compiling (`emit`)

| Status                   | Meaning                                                                                                                       |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| `invalid_key`            | The workflow key is empty, longer than 400 characters, or holds a character outside letters, digits, hyphens and underscores. |
| `duplicate_action_id`    | Two different steps produce or set one action id. Rename one, or pin an `id`.                                                 |
| `reserved_action_id`     | A step takes `trigger_node` or `exit_node`.                                                                                   |
| `invalid_action_id`      | An explicit `id` holds a character outside letters, digits, hyphens and underscores, or is empty or over 200 characters.      |
| `action_id_too_long`     | A derived id is over 200 characters. Shorten the name or pin an `id`.                                                         |
| `unnamed_action_id`      | The step name slugs to nothing. Give it an explicit `id`.                                                                     |
| `step_name_too_long`     | A step name is over 400 characters.                                                                                           |
| `reserved_action_type`   | A pass-through step uses the reserved action type `trigger` or `exit`. Use the workflow `on` field or `exit` field instead.   |
| `invalid_duration`       | A wait is not a positive number and a unit, or is zero.                                                                       |
| `duration_over_unit_cap` | A wait is over 60s, 60m, 24h or 30d. Use the larger unit, or split a wait over 30d.                                           |
| `empty_path`             | The workflow or a branch arm has no steps.                                                                                    |
| `invalid_email_sender`   | `from.integrationIds` is empty, holds more than ten ids, or holds a value that is not a positive integer.                     |
| `invalid_sender_address` | `from.email` is a literal that is not one address.                                                                            |
| `missing_secret`         | The variable a `secret` names is unset or empty in the environment that runs the push.                                        |
| `nested_secret`          | A `secret` sits inside a larger value, or anywhere in an email step.                                                          |
| `duplicate_variable_key` | Two variables share one key.                                                                                                  |
| `variables_too_large`    | The variables add up to more than 5120 bytes.                                                                                 |

## Credentials

| Status                     | Meaning                                                                                             |
| -------------------------- | --------------------------------------------------------------------------------------------------- |
| `missing_credentials`      | `push` found no key and project id together in the environment or in `~/.posthog/credentials.json`. |
| `invalid_host`             | The host is not a full URL with a scheme.                                                           |
| `insecure_host`            | The host is plain `http` and not loopback. Every request carries the key as a bearer token.         |
| `invalid_credentials_file` | `~/.posthog/credentials.json` is not valid JSON, or a field in it has the wrong type.               |

## Push guards

| Status              | Meaning                                                                                                                                                                        |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `path_mismatch`     | The workflow was last pushed from another path. A moved file needs `--allow-move`. A copied file needs its own key.                                                            |
| `path_not_resolved` | The push comes from outside a git checkout and no CI variables name one, so the path cannot be compared with the recorded one. Push from the checkout, or pass `--allow-move`. |
| `key_not_supported` | This PostHog does not store a workflow key, so a push cannot find the workflow again. Push to a PostHog that supports the key.                                                 |
| `ambiguous_key`     | The project holds more than one workflow with this key. Delete or re-key the extras in PostHog.                                                                                |

## Talking to PostHog

| Status             | Meaning                                                                                                                              |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------ |
| `network_error`    | The host could not be reached.                                                                                                       |
| `timeout`          | No response within 30 seconds.                                                                                                       |
| `redirect`         | PostHog answered with a redirect. The CLI never follows one with the key. Set `--host` to the final URL.                             |
| `invalid_response` | A success response the CLI cannot read. After a create or an update, check the workflow in PostHog before you run the command again. |
| `http_401`         | PostHog did not accept the API key. Check the key and that the host is the PostHog that issued it.                                   |
| `http_403`         | The key may not write workflows in this project. It needs the `hog_flow:write` scope.                                                |
| `http_400`         | PostHog refused the definition. `why` names the step. PostHog validates templates and inputs that `check` does not.                  |

Other HTTP response codes can occur dynamically. When PostHog sends a `fix`, the CLI prints it.

## Warnings that are not refusals

- `PostHog did not store the key` after a create: an older PostHog dropped the key, so the next push cannot find the workflow. Upgrade PostHog before you push again.
- `source not detected`: the push ran outside GitHub Actions, GitLab CI and a git checkout, so the source line cannot name a commit or branch. The push still lands.
