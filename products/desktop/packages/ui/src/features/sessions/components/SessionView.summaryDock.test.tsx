import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useSideQuestionStore } from "../sideQuestionStore";
import { SessionView } from "./SessionView";

vi.mock("@posthog/di/react", () => ({
  useService: () => ({
    askSideQuestion: vi.fn(),
    maybeRevertBypassMode: vi.fn(),
  }),
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));
vi.mock("./ThreadView", () => ({ ThreadView: () => null }));
vi.mock("../../billing/useSpendStop", () => ({
  useSpendStop: () => null,
  spendStopMessage: () => "",
}));
vi.mock("../hooks/useSessionEventsResidency", () => ({
  useSessionEventsResidency: vi.fn(),
}));
vi.mock("../hooks/useContextUsage", () => ({ useContextUsage: () => null }));
vi.mock("../hooks/useEditQueuedMessage", () => ({
  useCancelQueuedMessageEdit: () => vi.fn(),
}));
vi.mock("../hooks/useToggleMessagingMode", () => ({
  useToggleMessagingMode: () => vi.fn(),
}));
vi.mock("../sessionStore", () => ({
  useAdapterForTask: () => undefined,
  useConfigOptionForTask: () => undefined,
  useModeConfigOptionForTask: () => undefined,
  useModelConfigOptionForTask: () => undefined,
  usePendingPermissionsForTask: () => new Map(),
  useSessionSelector: (_taskId: string, selector: (s: unknown) => unknown) =>
    selector({ taskRunId: "run-1" }),
  useThoughtLevelConfigOptionForTask: () => undefined,
}));
vi.mock("../sessionViewStore", () => ({
  useSessionViewActions: () => ({ setShowRawLogs: vi.fn() }),
  useShowRawLogs: () => false,
}));
vi.mock("../useSession", () => ({ useSessionHandoffInProgress: () => false }));
vi.mock("../../feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => false,
}));
vi.mock("../../message-editor/draftStore", () => ({
  useDraftStore: (selector: (state: unknown) => unknown) =>
    selector({ actions: { requestFocus: vi.fn(), setContext: vi.fn() } }),
}));
vi.mock("../../message-editor/useAutoFocusOnTyping", () => ({
  useAutoFocusOnTyping: vi.fn(),
}));
vi.mock("../../settings/settingsStore", () => ({
  useSettingsStore: (selector?: (state: unknown) => unknown) => {
    const state = { allowBypassPermissions: false, useNewChatThread: false };
    return selector ? selector(state) : state;
  },
}));
vi.mock("../../workspace/useWorkspace", () => ({
  useIsWorkspaceCloudRun: () => false,
}));
vi.mock("../../../hooks/useConnectivity", () => ({
  useConnectivity: () => ({ isOnline: true }),
}));
vi.mock("../../../shell/pendingTaskPromptStore", () => ({
  pendingTaskPromptStoreApi: { clear: vi.fn() },
  usePendingTaskPrompt: () => null,
}));

describe("session summary dock", () => {
  beforeEach(() => {
    useSideQuestionStore.setState({
      byTaskId: {
        "task-1": {
          id: "s-1",
          question: "write a handoff",
          taskRunId: "run-1",
          kind: "summary",
          label: "Session summary",
          askedAt: Date.now(),
          status: "done",
          answer: "The goal is to ship the parser.",
        },
      },
    });
  });

  it("stays readable and dismissible when the session breaks", () => {
    render(
      <Theme>
        <SessionView
          events={[]}
          taskId="task-1"
          isRunning={false}
          hasError
          errorTitle="Session ended"
          onSendPrompt={async () => true}
          onCancelPrompt={vi.fn()}
        />
      </Theme>,
    );

    expect(screen.getByText("Session ended")).toBeInTheDocument();
    expect(
      screen.getByText("The goal is to ship the parser."),
    ).toBeInTheDocument();
    expect(screen.getByText("Copy")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Dismiss"));
    expect(useSideQuestionStore.getState().byTaskId["task-1"]).toBeUndefined();
  });
});
