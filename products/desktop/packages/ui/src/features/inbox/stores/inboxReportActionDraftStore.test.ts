import {
  resetInboxReportActionDrafts,
  useInboxReportActionDraftStore,
} from "@posthog/ui/features/inbox/stores/inboxReportActionDraftStore";
import { beforeEach, describe, expect, it } from "vitest";

describe("inboxReportActionDraftStore", () => {
  beforeEach(() => {
    useInboxReportActionDraftStore.setState({
      generation: 0,
      dismiss: {},
      resolve: {},
    });
  });

  it("discards callbacks from an earlier auth generation", () => {
    const { setDismiss } = useInboxReportActionDraftStore.getState();
    setDismiss(0, "report-1", {
      reason: "other",
      note: "Old session note",
      reopen: false,
    });

    resetInboxReportActionDrafts();
    setDismiss(0, "report-1", {
      reason: "other",
      note: "Old session note",
      reopen: true,
    });

    const state = useInboxReportActionDraftStore.getState();
    expect(state.generation).toBe(1);
    expect(state.dismiss).toEqual({});
  });
});
