# CI on PR label changes

Container Images CI and E2E Hobby CI react to two labels:

| Label                   | Behavior                                                                                                    |
| ----------------------- | ----------------------------------------------------------------------------------------------------------- |
| `hobby-preview`         | Adding it starts a preview build. Removing it cleans up the preview.                                        |
| `no-depot-docker-cache` | Adding or removing it reruns the image build and its eligible Hobby consumer with the updated cache policy. |

Other label changes skip both workflows' jobs and use a separate concurrency group.
They cannot cancel an active build, smoke test, or preview, or replace a pending run.
GitHub still dispatches these skipped runs because it cannot filter PR label triggers by label name.

An ignored label event uses `Ignore unrelated image label` instead of the required `Build Docker image` check name.
A skipped check counts as passing, so reusing the required name could hide a failed build from branch protection or Hobby's image waiter.
Normal pushes and relevant label events keep the required name and branch concurrency group.

This does not change draft-to-ready test coverage or the merge queue's checks.
See [the canceled image run](https://github.com/PostHog/posthog/actions/runs/34395495441) and [its replacement after a label change](https://github.com/PostHog/posthog/actions/runs/34395547613).
