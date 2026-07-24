import type { SourceProduct } from "@posthog/shared/types";
import type { SignalSourceValues } from "@posthog/ui/features/inbox/components/SignalSourceToggles";

export type ResponderAgentSource = keyof SignalSourceValues;

export interface ResponderAgentDefinition {
  source: ResponderAgentSource;
  sourceProduct: SourceProduct;
  label: string;
  description: string;
  docsUrl?: string;
  docsLabel?: string;
  alpha?: boolean;
}

export interface ResponderAgentGroup {
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
        docsUrl: "https://posthog.com/docs/error-tracking",
        docsLabel: "Error Tracking",
      },
      {
        source: "conversations",
        sourceProduct: "conversations",
        label: "Support",
        description: "Problems customers raise in support.",
        docsUrl: "https://posthog.com/docs/support",
        docsLabel: "Support",
      },
      {
        source: "health_checks",
        sourceProduct: "health_checks",
        label: "Health checks",
        description:
          "Instrumentation problems — missing events, proxy gaps, outdated SDKs.",
        docsUrl: "https://posthog.com/docs/sdk-health",
        docsLabel: "Health checks",
      },
      {
        source: "session_replay",
        sourceProduct: "session_replay",
        label: "Session Replay",
        description: "UX problems found in session recordings.",
        docsUrl: "https://posthog.com/docs/session-replay",
        docsLabel: "Session Replay",
        alpha: true,
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
      },
      {
        source: "linear",
        sourceProduct: "linear",
        label: "Linear",
        description: "Issues tracked in Linear.",
      },
      {
        source: "zendesk",
        sourceProduct: "zendesk",
        label: "Zendesk",
        description: "Incoming Zendesk tickets.",
      },
      {
        source: "pganalyze",
        sourceProduct: "pganalyze",
        label: "pganalyze",
        description:
          "Postgres performance problems – slow queries and bad indexes.",
      },
    ],
  },
];
