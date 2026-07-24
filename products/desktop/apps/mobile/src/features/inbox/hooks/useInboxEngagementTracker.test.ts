import { createElement } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// posthog-react-native pulls in real react-native at import time, which vitest
// can't parse. The hook only uses `Analytics.track`, which is passed in by the
// caller — so mocking the module to a no-op keeps the import graph quiet.
vi.mock("posthog-react-native", () => ({
  usePostHog: () => null,
}));

import { ANALYTICS_EVENTS, type Analytics } from "@/lib/analytics";
import type { SignalReport } from "../types";
import {
  type InboxEngagementTracker,
  type UseInboxEngagementTrackerOptions,
  useInboxEngagementTracker,
} from "./useInboxEngagementTracker";

function makeReport(overrides: Partial<SignalReport> = {}): SignalReport {
  return {
    id: "r1",
    title: "Report 1",
    summary: null,
    status: "ready",
    total_weight: 0,
    signal_count: 0,
    created_at: "2026-01-01T12:00:00Z",
    updated_at: "2026-01-01T12:00:00Z",
    artefact_count: 0,
    priority: "P1",
    actionability: "immediately_actionable",
    source_products: ["error_tracking"],
    ...overrides,
  };
}

function renderTracker(initial: UseInboxEngagementTrackerOptions) {
  const trackerRef: { current: InboxEngagementTracker | null } = {
    current: null,
  };
  let currentOptions = initial;
  function Wrapper() {
    trackerRef.current = useInboxEngagementTracker(currentOptions);
    return null;
  }
  let renderer: ReactTestRenderer | null = null;
  act(() => {
    renderer = create(createElement(Wrapper));
  });
  return {
    tracker: () => {
      if (!trackerRef.current) throw new Error("tracker not initialised");
      return trackerRef.current;
    },
    rerender: (next: UseInboxEngagementTrackerOptions) => {
      currentOptions = next;
      act(() => {
        renderer?.update(createElement(Wrapper));
      });
    },
    unmount: () => {
      act(() => {
        renderer?.unmount();
      });
    },
  };
}

describe("useInboxEngagementTracker", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T13:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("fires OPENED on mount with the right snapshot of report fields", () => {
    const track = vi.fn();
    const analytics: Analytics = { track };
    const report = makeReport();
    renderTracker({
      analytics,
      report,
      rank: 2,
      listSize: 5,
      openMethod: "click",
      previousReportId: "prev-1",
    });
    expect(track).toHaveBeenCalledWith(
      ANALYTICS_EVENTS.INBOX_REPORT_OPENED,
      expect.objectContaining({
        report_id: "r1",
        report_title: "Report 1",
        report_age_hours: 1,
        status: "ready",
        priority: "P1",
        actionability: "immediately_actionable",
        source_products: ["error_tracking"],
        rank: 2,
        list_size: 5,
        open_method: "click",
        previous_report_id: "prev-1",
      }),
    );
  });

  it("fires CLOSED on unmount with time_spent, scrolled, close_method", () => {
    const track = vi.fn();
    const report = makeReport();
    const hook = renderTracker({
      analytics: { track },
      report,
      rank: 0,
      listSize: 1,
      openMethod: "click",
      previousReportId: null,
    });
    act(() => {
      hook.tracker().signalScroll();
    });
    vi.advanceTimersByTime(2500);
    hook.unmount();
    const closeCall = track.mock.calls.find(
      ([name]) => name === ANALYTICS_EVENTS.INBOX_REPORT_CLOSED,
    );
    expect(closeCall).toBeDefined();
    expect(closeCall?.[1]).toMatchObject({
      report_id: "r1",
      scrolled: true,
      close_method: "deselected",
      priority: "P1",
      actionability: "immediately_actionable",
    });
    expect((closeCall?.[1] as { time_spent_ms: number }).time_spent_ms).toBe(
      2500,
    );
  });

  it("fires SCROLLED at most once per open", () => {
    const track = vi.fn();
    const hook = renderTracker({
      analytics: { track },
      report: makeReport(),
      rank: 0,
      listSize: 1,
      openMethod: "click",
      previousReportId: null,
    });
    act(() => {
      hook.tracker().signalScroll();
      hook.tracker().signalScroll();
      hook.tracker().signalScroll();
    });
    const scrollCalls = track.mock.calls.filter(
      ([name]) => name === ANALYTICS_EVENTS.INBOX_REPORT_SCROLLED,
    );
    expect(scrollCalls).toHaveLength(1);
  });

  it("signalAction inherits rank/list_size/priority/actionability from the current open", () => {
    const track = vi.fn();
    const report = makeReport({ priority: "P0" });
    const hook = renderTracker({
      analytics: { track },
      report,
      rank: 3,
      listSize: 7,
      openMethod: "click",
      previousReportId: null,
    });
    act(() => {
      hook.tracker().signalAction({
        report_id: "r1",
        report_title: "Report 1",
        report_age_hours: 1,
        action_type: "create_pr",
        surface: "detail_pane",
        is_bulk: false,
        bulk_size: 1,
      });
    });
    const actionCall = track.mock.calls.find(
      ([name]) => name === ANALYTICS_EVENTS.INBOX_REPORT_ACTION,
    );
    expect(actionCall?.[1]).toMatchObject({
      rank: 3,
      list_size: 7,
      priority: "P0",
      actionability: "immediately_actionable",
    });
  });

  it("does not re-fire OPENED/CLOSED when rank/listSize/report change while the same report stays open", () => {
    // Regression for a background-refetch spike: rank, listSize, and the
    // report shape are inputs to OPENED but only `reportId` should gate the
    // open/close lifecycle.
    const track = vi.fn();
    const report = makeReport();
    const hook = renderTracker({
      analytics: { track },
      report,
      rank: 2,
      listSize: 5,
      openMethod: "click",
      previousReportId: null,
    });
    const openedBefore = track.mock.calls.filter(
      ([name]) => name === ANALYTICS_EVENTS.INBOX_REPORT_OPENED,
    ).length;
    const closedBefore = track.mock.calls.filter(
      ([name]) => name === ANALYTICS_EVENTS.INBOX_REPORT_CLOSED,
    ).length;
    hook.rerender({
      analytics: { track },
      report: makeReport({ priority: "P2", actionability: "not_actionable" }),
      rank: 4,
      listSize: 6,
      openMethod: "click",
      previousReportId: null,
    });
    const openedAfter = track.mock.calls.filter(
      ([name]) => name === ANALYTICS_EVENTS.INBOX_REPORT_OPENED,
    ).length;
    const closedAfter = track.mock.calls.filter(
      ([name]) => name === ANALYTICS_EVENTS.INBOX_REPORT_CLOSED,
    ).length;
    expect(openedAfter).toBe(openedBefore);
    expect(closedAfter).toBe(closedBefore);
  });

  it("signalAction lets explicit overrides win for a different report", () => {
    const track = vi.fn();
    const hook = renderTracker({
      analytics: { track },
      report: makeReport(),
      rank: 0,
      listSize: 1,
      openMethod: "click",
      previousReportId: null,
    });
    act(() => {
      hook.tracker().signalAction({
        report_id: "other-report",
        report_title: "Other",
        report_age_hours: 0,
        action_type: "dismiss",
        surface: "toolbar",
        is_bulk: false,
        bulk_size: 1,
        rank: 9,
        list_size: 12,
        priority: "P4",
        actionability: "not_actionable",
        dismissal_reason: "other",
        dismissal_note: "junk",
      });
    });
    const actionCall = track.mock.calls.find(
      ([name]) => name === ANALYTICS_EVENTS.INBOX_REPORT_ACTION,
    );
    expect(actionCall?.[1]).toMatchObject({
      report_id: "other-report",
      rank: 9,
      list_size: 12,
      priority: "P4",
      actionability: "not_actionable",
      dismissal_reason: "other",
      dismissal_note: "junk",
    });
  });
});
