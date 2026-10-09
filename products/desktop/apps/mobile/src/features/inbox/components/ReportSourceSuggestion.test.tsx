import type {
  SignalReport,
  SignalReportSourceSuggestion,
} from "@posthog/shared/domain-types";
import { createElement } from "react";
import { act, create, type ReactTestInstance } from "react-test-renderer";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  track: vi.fn(),
  openExternalUrl: vi.fn(),
}));

vi.mock("@/features/auth", () => ({
  useAuthStore: () => ({
    projectId: 42,
    cloudRegion: "us",
    getCloudUrlFromRegion: () => "https://us.posthog.com",
  }),
}));

vi.mock("@/lib/analytics", () => ({
  ANALYTICS_EVENTS: {
    INBOX_REPORT_SOURCE_SUGGESTION_SHOWN:
      "Inbox report source suggestion shown",
    INBOX_REPORT_SOURCE_SUGGESTION_CLICKED:
      "Inbox report source suggestion clicked",
  },
  computeReportAgeHours: () => 1,
  useAnalytics: () => ({ track: mocks.track }),
}));

vi.mock("@/lib/openExternalUrl", () => ({
  openExternalUrl: (url: string) => mocks.openExternalUrl(url),
}));

vi.mock("@/lib/theme", () => ({
  useThemeColors: () => ({ gray: { 9: "#888", 11: "#555" } }),
}));

import { ReportSourceSuggestion } from "./ReportSourceSuggestion";

function makeReport(): SignalReport {
  return {
    id: "report-1",
    created_at: "2026-10-01T00:00:00Z",
    priority: "P1",
    actionability: "immediately_actionable",
    implementation_pr_url: null,
  } as SignalReport;
}

function render(suggestion: SignalReportSourceSuggestion) {
  let renderer: ReturnType<typeof create> | null = null;
  act(() => {
    renderer = create(
      createElement(ReportSourceSuggestion, {
        report: makeReport(),
        suggestion,
      }),
    );
  });
  if (!renderer) throw new Error("Renderer not created");
  return renderer as ReturnType<typeof create>;
}

function findByLabel(renderer: ReturnType<typeof create>, label: string) {
  return renderer.root.findAll(
    (node: ReactTestInstance) => node.props.accessibilityLabel === label,
  );
}

describe("ReportSourceSuggestion", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders a known product with its action label", () => {
    const renderer = render({
      product: "logs",
      reason: "Logs would show the timeout.",
    });

    expect(findByLabel(renderer, "Set up logs").length).toBeGreaterThan(0);
    expect(mocks.track).toHaveBeenCalledWith(
      "Inbox report source suggestion shown",
      expect.objectContaining({
        report_id: "report-1",
        product: "logs",
        has_pr: false,
      }),
    );
  });

  it("renders nothing for an unknown product", () => {
    const renderer = render({
      // biome-ignore lint/suspicious/noExplicitAny: force an unknown product to assert the client-side gate.
      product: "unknown_product" as any,
      reason: "Would help somehow.",
    });

    expect(renderer.toJSON()).toBeNull();
    expect(mocks.track).not.toHaveBeenCalled();
  });

  it("fires the click event and opens the product URL on press", () => {
    const renderer = render({
      product: "logs",
      reason: "Logs would show the timeout.",
    });

    const [button] = findByLabel(renderer, "Set up logs");
    act(() => {
      button.props.onPress();
    });

    expect(mocks.openExternalUrl).toHaveBeenCalledWith(
      "https://us.posthog.com/project/42/logs",
    );
    expect(mocks.track).toHaveBeenCalledWith(
      "Inbox report source suggestion clicked",
      expect.objectContaining({
        report_id: "report-1",
        product: "logs",
      }),
    );
  });
});
