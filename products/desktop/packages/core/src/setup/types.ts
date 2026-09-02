export type DiscoveredTaskSource = "agent" | "enricher";

export interface DiscoveredTask {
  id: string;
  repoPath?: string;
  title: string;
  description: string;
  category:
    | "bug"
    | "security"
    | "dead_code"
    | "duplication"
    | "performance"
    | "stale_feature_flag"
    | "error_tracking"
    | "event_tracking"
    | "funnel"
    | "posthog_setup"
    | "experiment";
  source: DiscoveredTaskSource;
  file?: string;
  lineHint?: number;
  impact?: string;
  recommendation?: string;
  prompt?: string;
}

export const BASE_CATEGORY_ENUM = [
  "bug",
  "security",
  "dead_code",
  "duplication",
  "performance",
  "stale_feature_flag",
  "error_tracking",
  "event_tracking",
  "funnel",
] as const;

export function buildTaskDiscoverySchema({
  includeExperiments,
}: {
  includeExperiments: boolean;
}): Record<string, unknown> {
  const categoryEnum = includeExperiments
    ? [...BASE_CATEGORY_ENUM, "experiment"]
    : [...BASE_CATEGORY_ENUM];

  return {
    type: "object",
    properties: {
      tasks: {
        type: "array",
        items: {
          type: "object",
          properties: {
            id: {
              type: "string",
              description: "A short kebab-case identifier",
            },
            title: {
              type: "string",
              description:
                "Short, action-oriented header — under 60 characters. No file paths or line numbers.",
            },
            description: {
              type: "string",
              description:
                "A clear paragraph (2–4 sentences) describing the problem: what's wrong and the conditions under which it manifests. Do NOT include the file path or line number — those go in the file/lineHint fields. For experiment-category tasks, state the hypothesis being tested instead of a problem.",
            },
            category: {
              type: "string",
              enum: categoryEnum,
            },
            file: {
              type: "string",
              description: "Relative file path where the issue lives",
            },
            lineHint: {
              type: "integer",
              description: "Approximate line number",
            },
            impact: {
              type: "string",
              description:
                "Why this matters — concrete impact, blast radius, or risk. 1–3 sentences. For experiment-category tasks, state the metric you would measure and the outcome a winning variant would produce.",
            },
            recommendation: {
              type: "string",
              description:
                "Suggested approach to fix, in plain prose. 2–4 sentences pointing at the right shape of the fix without writing the patch. Reference any specific functions, types, or files involved. For experiment-category tasks, describe the proposed control and test variants concretely.",
            },
          },
          required: [
            "id",
            "title",
            "description",
            "category",
            "impact",
            "recommendation",
          ],
        },
        maxItems: 4,
      },
    },
    required: ["tasks"],
  };
}
