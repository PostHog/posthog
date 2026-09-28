import type { SignalTeamConfig } from "@posthog/shared/types";

/** What the server applies when the label is on but the team named none. */
export const DEFAULT_PULL_REQUEST_LABEL = "self-driving";

/** GitHub refuses a longer label, and the column stops at the same length. */
export const PULL_REQUEST_LABEL_MAX_LENGTH = 50;

/** The fields a label write may carry. Either one can travel on its own. */
export interface PullRequestLabelUpdate {
  pull_request_label_enabled?: boolean;
  pull_request_label?: string | null;
}

export type PullRequestLabelParseResult =
  | { ok: true; value: string | null }
  | { ok: false; error: string };

/**
 * Turn the text field into a value for `pull_request_label`. Empty text means
 * `null`, which the server reads as the default label. Anything else must fit
 * the GitHub label length.
 */
export function parsePullRequestLabel(
  input: string,
): PullRequestLabelParseResult {
  const trimmed = input.trim();
  if (trimmed === "") {
    return { ok: true, value: null };
  }

  if (trimmed.length > PULL_REQUEST_LABEL_MAX_LENGTH) {
    return {
      ok: false,
      error: `Use ${PULL_REQUEST_LABEL_MAX_LENGTH} characters or fewer.`,
    };
  }

  return { ok: true, value: trimmed };
}

/** Whether self-driving labels the pull requests it opens. */
export function pullRequestLabelEnabled(
  config: SignalTeamConfig | null | undefined,
): boolean {
  return config?.pull_request_label_enabled ?? false;
}

/** The saved label as text for the input field; empty string when unset. */
export function pullRequestLabelFieldValue(
  config: SignalTeamConfig | null | undefined,
): string {
  return config?.pull_request_label ?? "";
}

/** The label GitHub receives, which is the default while no name is saved. */
export function effectivePullRequestLabel(
  config: SignalTeamConfig | null | undefined,
): string {
  return (
    pullRequestLabelFieldValue(config).trim() || DEFAULT_PULL_REQUEST_LABEL
  );
}

/** One-line summary of the current state, shown under the control. */
export function describePullRequestLabel(
  config: SignalTeamConfig | null | undefined,
): string {
  if (!pullRequestLabelEnabled(config)) {
    return "Pull requests open without a label.";
  }
  return `Pull requests get the "${effectivePullRequestLabel(config)}" label.`;
}
