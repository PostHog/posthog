import type {
  SignalTeamConfig,
  SignalUserAutonomyConfig,
} from "@posthog/shared/types";

/** How a self-driving pull request opens on GitHub. */
export type PullRequestReadyState = "draft" | "ready";

/** A reviewer's own choice, where `default` follows the project setting. */
export type PullRequestReadyChoice = PullRequestReadyState | "default";

/** Draft is the server default, so a project with no config saved yet reads as draft. */
export function teamPullRequestReadyState(
  config: SignalTeamConfig | null | undefined,
): PullRequestReadyState {
  return config?.default_open_pull_request_ready ? "ready" : "draft";
}

/**
 * Read the reviewer's override. `null` and `undefined` both mean "no preference",
 * which follows the project rather than pinning draft.
 */
export function userPullRequestReadyChoice(
  config: SignalUserAutonomyConfig | null | undefined,
): PullRequestReadyChoice {
  const mine = config?.github_open_pull_request_ready;
  if (mine == null) {
    return "default";
  }
  return mine ? "ready" : "draft";
}

/** Turn a segmented-control choice back into the value the API stores. */
export function pullRequestReadyChoiceToValue(
  choice: PullRequestReadyChoice,
): boolean | null {
  if (choice === "default") {
    return null;
  }
  return choice === "ready";
}

/** What a pull request created for this reviewer actually opens as. */
export function effectivePullRequestReadyState(
  teamConfig: SignalTeamConfig | null | undefined,
  userConfig: SignalUserAutonomyConfig | null | undefined,
): PullRequestReadyState {
  const mine = userPullRequestReadyChoice(userConfig);
  return mine === "default" ? teamPullRequestReadyState(teamConfig) : mine;
}
