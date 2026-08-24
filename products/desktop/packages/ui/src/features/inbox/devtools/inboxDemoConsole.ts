import { resolveService } from "@posthog/di/container";
import type {
  SignalReport,
  SignalReportArtefact,
  SignalReportArtefactsResponse,
  SignalReportsResponse,
} from "@posthog/shared/domain-types";
import { logger } from "@posthog/ui/shell/logger";
import {
  IMPERATIVE_QUERY_CLIENT,
  type ImperativeQueryClient,
} from "@posthog/ui/shell/queryClient";

function queryClientInstance(): ImperativeQueryClient {
  return resolveService<ImperativeQueryClient>(IMPERATIVE_QUERY_CLIENT);
}

type DemoSeedMode = "rich" | "empty" | "artefacts-unavailable";
type DemoAction = "help" | "seed" | "clear";

type InboxDemoConsoleCommand = (
  action?: DemoAction,
  mode?: DemoSeedMode,
) => string;

const log = logger.scope("inbox-demo-console");

const inboxReportsKey = ["inbox", "signal-reports", "list"] as const;
const inboxArtefactsKey = (reportId: string) =>
  ["inbox", "signal-reports", reportId, "artefacts"] as const;

function iso(minutesAgo: number): string {
  return new Date(Date.now() - minutesAgo * 60 * 1000).toISOString();
}

function getDemoReports(): SignalReport[] {
  return [
    {
      id: "demo-signal-checkout-errors",
      title: "Checkout errors after plan upgrade",
      summary:
        "Users hit a client-side exception after completing plan upgrades, mostly on Safari 17.",
      status: "ready",
      total_weight: 79,
      signal_count: 31,
      created_at: iso(1800),
      updated_at: iso(8),
      artefact_count: 3,
    },
    {
      id: "demo-signal-empty-state-loop",
      title: "Onboarding flow loops from invite page",
      summary:
        "A subset of invited users are redirected back to onboarding, causing repeated drop-offs.",
      status: "ready",
      total_weight: 52,
      signal_count: 11,
      created_at: iso(2200),
      updated_at: iso(35),
      artefact_count: 2,
    },
    {
      id: "demo-signal-ux-paper-cut",
      title: "Tooltip misalignment on smaller laptop screens",
      summary:
        "Not a blocker, but repeated UI friction in replay segments around tooltip placement.",
      status: "ready",
      total_weight: 24,
      signal_count: 4,
      created_at: iso(3600),
      updated_at: iso(140),
      artefact_count: 1,
    },
  ];
}

function artefact(
  id: string,
  sessionId: string,
  content: string,
  startTimeMinutesAgo: number,
): SignalReportArtefact {
  const start = iso(startTimeMinutesAgo);
  const end = new Date(
    Date.now() - (startTimeMinutesAgo - 3) * 60 * 1000,
  ).toISOString();

  return {
    id,
    type: "video_segment",
    created_at: start,
    content: {
      session_id: sessionId,
      start_time: start,
      end_time: end,
      distinct_id: `demo-user-${id}`,
      content,
      distance_to_centroid: 0.12,
    },
  };
}

function getDemoArtefacts(
  mode: DemoSeedMode,
): Record<string, SignalReportArtefactsResponse> {
  const base: Record<string, SignalReportArtefactsResponse> = {
    "demo-signal-checkout-errors": {
      results: [
        artefact(
          "demo-art-1",
          "demo-session-1",
          "Upgrade confirmation shows, then a TypeError is thrown on post-upgrade route hydration.",
          12,
        ),
        artefact(
          "demo-art-2",
          "demo-session-2",
          "Session replay shows multiple retries followed by a payment history panel crash.",
          45,
        ),
        artefact(
          "demo-art-3",
          "demo-session-3",
          "Error boundary catches an undefined state read in checkout success handler.",
          93,
        ),
      ],
      count: 3,
    },
    "demo-signal-empty-state-loop": {
      results: [
        artefact(
          "demo-art-4",
          "demo-session-4",
          "Invite accept action returns 200 but front-end route guard redirects back to onboarding start.",
          28,
        ),
        artefact(
          "demo-art-5",
          "demo-session-5",
          "Affected users bounce between '/invite' and '/setup/profile' after auth refresh.",
          61,
        ),
      ],
      count: 2,
    },
    "demo-signal-ux-paper-cut": {
      results: [
        artefact(
          "demo-art-6",
          "demo-session-6",
          "Tooltip anchors to stale element position after browser zoom and container resize.",
          150,
        ),
      ],
      count: 1,
    },
  };

  if (mode === "artefacts-unavailable") {
    base["demo-signal-checkout-errors"] = {
      results: [],
      count: 0,
      unavailableReason: "invalid_payload",
    };
  }

  return base;
}

function setInboxDemoData(mode: DemoSeedMode): void {
  const reports = mode === "empty" ? [] : getDemoReports();
  const reportsPayload: SignalReportsResponse = {
    results: reports,
    count: reports.length,
  };

  const queryClient = queryClientInstance();
  queryClient.setQueryData(inboxReportsKey, reportsPayload);

  const existingArtefactQueries = queryClient.getQueriesData({
    queryKey: ["inbox", "signal-reports"],
  });
  for (const [queryKey] of existingArtefactQueries) {
    if (Array.isArray(queryKey) && queryKey.at(-1) === "artefacts") {
      queryClient.removeQueries({ queryKey, exact: true });
    }
  }

  if (mode !== "empty") {
    const artefactsByReportId = getDemoArtefacts(mode);
    for (const [reportId, payload] of Object.entries(artefactsByReportId)) {
      queryClient.setQueryData(inboxArtefactsKey(reportId), payload);
    }
  }
}

function clearInboxDemoData(): void {
  const queryClient = queryClientInstance();
  queryClient.removeQueries({
    queryKey: ["inbox", "signal-reports"],
    exact: false,
  });
  queryClient.invalidateQueries({
    queryKey: ["inbox", "signal-reports"],
    exact: false,
  });
}

function printHelp(): string {
  const help =
    "Code inbox demo command ready. Use window.__codeInboxDemo('seed'), window.__codeInboxDemo('seed', 'artefacts-unavailable'), window.__codeInboxDemo('seed', 'empty'), or window.__codeInboxDemo('clear').";
  log.info(help);
  return help;
}

export function registerInboxDemoConsoleCommand(): void {
  if (import.meta.env.PROD || typeof window === "undefined") {
    return;
  }

  if (typeof window.__codeInboxDemo === "function") {
    return;
  }

  const command: InboxDemoConsoleCommand = (
    action: DemoAction = "help",
    mode: DemoSeedMode = "rich",
  ) => {
    if (action === "help") {
      return printHelp();
    }

    if (action === "clear") {
      clearInboxDemoData();
      const message = "Cleared inbox demo data. Live API data will be used.";
      log.info(message);
      return message;
    }

    setInboxDemoData(mode);
    const message = `Loaded inbox demo data in '${mode}' mode.`;
    log.info(message);
    return message;
  };

  Object.defineProperty(window, "__codeInboxDemo", {
    value: command,
    configurable: true,
    writable: false,
  });
}

declare global {
  interface Window {
    __codeInboxDemo?: InboxDemoConsoleCommand;
  }
}
