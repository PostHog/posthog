import type {
  SourceProduct,
  ToggleableSourceProduct,
} from "@posthog/shared/types";

/**
 * Sources that render as a card on this page. Every toggleable source product, plus Replay
 * Vision, which has no config row to switch and is driven entirely by its scanners.
 */
export type ResponderAgentSource = ToggleableSourceProduct | "replay_vision";

export interface ResponderAgentDefinition {
  source: ResponderAgentSource;
  sourceProduct: SourceProduct;
  label: string;
  description: string;
  /** Opens the expanded card. Says what triggers a signal, not what the source watches. */
  detail?: string;
  /** Plural noun for the things listed inside the card, e.g. "scanners". */
  entityNoun?: string;
  /**
   * The user creates these entities, so the list has no fixed length and the card gets no
   * master switch: one would write to every entity at once, and switching back would not
   * restore the earlier subset. A product-defined list keeps its master switch.
   */
  entitiesAreUserCreated?: boolean;
  /** PostHog path where these entities are created and configured. */
  manageUrl?: string;
  docsUrl?: string;
  docsLabel?: string;
  alpha?: boolean;
}

interface ResponderAgentGroup {
  label: string;
  agents: ResponderAgentDefinition[];
}

export const RESPONDER_AGENT_GROUPS: ResponderAgentGroup[] = [
  {
    label: "PostHog data",
    agents: [
      {
        source: "error_tracking",
        sourceProduct: "error_tracking",
        label: "Error Tracking",
        description: "Bugs surfaced as new errors, regressions, and spikes.",
        detail:
          "Each type below is a separate trigger, so turning one off leaves the others watching.",
        entityNoun: "signal types",
        docsUrl: "https://posthog.com/docs/error-tracking",
        docsLabel: "Error Tracking",
      },
      {
        source: "conversations",
        sourceProduct: "conversations",
        label: "Support",
        description: "Problems customers raise in support.",
        detail: "Only open tickets are read.",
        docsUrl: "https://posthog.com/docs/support",
        docsLabel: "Support",
      },
      {
        source: "replay_vision",
        sourceProduct: "replay_vision",
        label: "Replay vision",
        description:
          "UX problems your scanners find while watching recordings.",
        detail:
          "Switching a scanner on here lets its findings start agent research. Scouts read observations from any scanner either way.",
        entityNoun: "scanners",
        entitiesAreUserCreated: true,
        manageUrl: "/replay-vision",
        docsUrl: "https://posthog.com/docs/replay-vision",
        docsLabel: "Replay vision",
      },
      {
        source: "health_checks",
        sourceProduct: "health_checks",
        label: "Health checks",
        description:
          "Instrumentation problems — missing events, proxy gaps, outdated SDKs.",
        detail:
          "Checks your setup for missing events, an outdated SDK, proxy problems, failed warehouse syncs, and missing source maps.",
        docsUrl: "https://posthog.com/docs/sdk-health",
        docsLabel: "Health checks",
      },
      {
        source: "llm_analytics",
        sourceProduct: "llm_analytics",
        label: "AI observability",
        description:
          "Quality problems in your AI features. Set up evaluations to start getting signals.",
        detail:
          "Completed eval reports can become signals. Choose which reports run, and when, in AI observability.",
        docsUrl: "https://posthog.com/docs/ai-evals",
        docsLabel: "evaluations",
      },
    ],
  },
  {
    label: "Connected tools",
    agents: [
      {
        source: "github",
        sourceProduct: "github",
        label: "GitHub Issues",
        description: "Issues filed in GitHub.",
        detail:
          "Reads the issues from the GitHub repositories you sync to the warehouse.",
      },
      {
        source: "linear",
        sourceProduct: "linear",
        label: "Linear",
        description: "Issues tracked in Linear.",
        detail:
          "Reads the issues from the Linear workspace you sync to the warehouse.",
      },
      {
        source: "zendesk",
        sourceProduct: "zendesk",
        label: "Zendesk",
        description: "Incoming Zendesk tickets.",
        detail:
          "Reads the tickets from the Zendesk account you sync to the warehouse.",
      },
      {
        source: "pganalyze",
        sourceProduct: "pganalyze",
        label: "pganalyze",
        description:
          "Postgres performance problems – slow queries and bad indexes.",
        detail:
          "Reads the issues from the pganalyze account you sync to the warehouse.",
      },
    ],
  },
];
