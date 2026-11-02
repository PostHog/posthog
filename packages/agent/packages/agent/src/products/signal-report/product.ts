import type { AgentProduct } from "../../sdk/product";
import { buildPullRequestFooter } from "../../sdk/product";

export const SIGNAL_REPORT_ORIGIN = "signal_report";

export function signalReportProduct(): AgentProduct {
  return {
    id: SIGNAL_REPORT_ORIGIN,
    configureSession: ({ launch }) => {
      const threadUrl = launch.launchOptions.slack_thread_url;
      const source =
        typeof threadUrl === "string" && threadUrl
          ? { label: "Slack thread", url: threadUrl }
          : launch.source;
      return {
        pullRequests: {
          autoPublish: true,
          footer: buildPullRequestFooter(launch, { automated: true, source }),
        },
      };
    },
  };
}
