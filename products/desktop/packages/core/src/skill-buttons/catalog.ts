import type { SkillButtonId } from "@posthog/shared/analytics-events";

export type { SkillButtonId };

export interface SkillButtonCatalogEntry {
  id: SkillButtonId;
  label: string;
  prompt: string;
  color: string;
  actionTitle: string;
  actionDescription: string;
  tooltip: string;
}

export const SKILL_BUTTON_CATALOG: Record<
  SkillButtonId,
  SkillButtonCatalogEntry
> = {
  "add-analytics": {
    id: "add-analytics",
    label: "Track events",
    prompt: "/instrument-product-analytics",
    color: "#2F80FA",
    actionTitle: "Adding analytics",
    actionDescription: "to measure how this change performs in production.",
    tooltip:
      "Instrument PostHog events so you can measure this change in production",
  },
  "create-feature-flags": {
    id: "create-feature-flags",
    label: "Add feature flag",
    prompt: "/instrument-feature-flags",
    color: "#30ABC6",
    actionTitle: "Creating a feature flag",
    actionDescription:
      "to roll this out safely and toggle it without a redeploy.",
    tooltip:
      "Gate this change behind a PostHog feature flag for a safe rollout",
  },
  "run-experiment": {
    id: "run-experiment",
    label: "Run experiment",
    prompt:
      "Set up a PostHog experiment for the feature in this task. Use the PostHog MCP to create the feature flag with control and test variants, then create the experiment in draft with a clear hypothesis and primary metric tied to the feature's success. Wire the variant into the code via posthog.getFeatureFlag. Only launch the experiment if the feature is already live in production — otherwise leave it in draft and tell me to launch it after this is merged and deployed.",
    color: "#B62AD9",
    actionTitle: "Setting up an experiment",
    actionDescription:
      "with control and test variants tied to a primary metric, ready to launch once this ships.",
    tooltip:
      "Scaffold a PostHog A/B experiment with control and test variants tied to a primary metric",
  },
  "add-error-tracking": {
    id: "add-error-tracking",
    label: "Track errors",
    prompt: "/instrument-error-tracking",
    color: "#BF8113",
    actionTitle: "Adding error tracking",
    actionDescription:
      "so exceptions surface in PostHog with stack traces and source maps.",
    tooltip:
      "Capture exceptions in PostHog with stack traces so issues surface quickly in production",
  },
  "instrument-llm-calls": {
    id: "instrument-llm-calls",
    label: "Trace LLM calls",
    prompt: "/instrument-llm-analytics",
    color: "#B029D2",
    actionTitle: "Instrumenting LLM calls",
    actionDescription:
      "for visibility into prompts, tokens, latency, and costs.",
    tooltip:
      "Inspect traces, spans, latency, usage, and per-user costs for AI-powered features",
  },
  "add-logging": {
    id: "add-logging",
    label: "Capture logs",
    prompt: "/instrument-logs",
    color: "#C92474",
    actionTitle: "Adding logging",
    actionDescription:
      "so structured log events flow into PostHog for inspection and debugging.",
    tooltip:
      "Capture structured application logs in PostHog for inspection and debugging",
  },
};

export const SKILL_BUTTON_ORDER: SkillButtonId[] = [
  "add-analytics",
  "add-logging",
  "add-error-tracking",
  "instrument-llm-calls",
  "create-feature-flags",
  "run-experiment",
];

export const SKILL_BUTTON_IDS: ReadonlySet<SkillButtonId> = new Set(
  Object.keys(SKILL_BUTTON_CATALOG) as SkillButtonId[],
);

export function isSkillButtonId(value: unknown): value is SkillButtonId {
  return (
    typeof value === "string" && SKILL_BUTTON_IDS.has(value as SkillButtonId)
  );
}
