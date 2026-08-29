import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SessionView } from "../sessions/components/SessionView";

vi.mock("@posthog/di/react", () => ({
  useService: () => ({ maybeRevertBypassMode: vi.fn() }),
}));

vi.mock("../sessions/components/ThreadView", async () => {
  const { PlanContent } = await import("./PlanContent");
  return {
    ThreadView: () => (
      <PlanContent id="test-plan" plan="# Test plan\n\nShip the fix." />
    ),
  };
});

vi.mock("../billing/useSpendStop", () => ({
  useSpendStop: () => null,
  spendStopMessage: () => "",
}));
vi.mock("../sessions/hooks/useSessionEventsResidency", () => ({
  useSessionEventsResidency: vi.fn(),
}));
vi.mock("../sessions/hooks/useContextUsage", () => ({
  useContextUsage: () => null,
}));
vi.mock("../sessions/hooks/useEditQueuedMessage", () => ({
  useCancelQueuedMessageEdit: () => vi.fn(),
}));
vi.mock("../sessions/hooks/useToggleMessagingMode", () => ({
  useToggleMessagingMode: () => vi.fn(),
}));
vi.mock("../sessions/sessionStore", () => ({
  useAdapterForTask: () => undefined,
  useConfigOptionForTask: () => undefined,
  useModeConfigOptionForTask: () => undefined,
  useModelConfigOptionForTask: () => undefined,
  usePendingPermissionsForTask: () => new Map(),
  useSessionSelector: () => false,
  useThoughtLevelConfigOptionForTask: () => undefined,
}));
vi.mock("../sessions/sessionViewStore", () => ({
  useSessionViewActions: () => ({ setShowRawLogs: vi.fn() }),
  useShowRawLogs: () => false,
}));
vi.mock("../sessions/useSession", () => ({
  useSessionHandoffInProgress: () => false,
}));
vi.mock("../feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => false,
}));
vi.mock("../message-editor/draftStore", () => ({
  useDraftStore: (selector: (state: unknown) => unknown) =>
    selector({ actions: { requestFocus: vi.fn(), setContext: vi.fn() } }),
}));
vi.mock("../message-editor/useAutoFocusOnTyping", () => ({
  useAutoFocusOnTyping: vi.fn(),
}));
vi.mock("../settings/settingsStore", () => ({
  useSettingsStore: (selector?: (state: unknown) => unknown) => {
    const state = { allowBypassPermissions: false, useNewChatThread: false };
    return selector ? selector(state) : state;
  },
}));
vi.mock("../workspace/useWorkspace", () => ({
  useIsWorkspaceCloudRun: () => false,
}));
vi.mock("../../hooks/useConnectivity", () => ({
  useConnectivity: () => ({ isOnline: true }),
}));
vi.mock("../../shell/pendingTaskPromptStore", () => ({
  pendingTaskPromptStoreApi: { clear: vi.fn() },
  usePendingTaskPrompt: () => null,
}));

function renderPlanSession() {
  return render(
    <Theme>
      <SessionView
        events={[]}
        isRunning={false}
        hideInput
        onSendPrompt={async () => true}
        onCancelPrompt={vi.fn()}
      />
    </Theme>,
  );
}

describe("PlanContent fullscreen", () => {
  it("expands into the portal owned by SessionView", async () => {
    const user = userEvent.setup();
    renderPlanSession();

    await user.click(
      screen.getByRole("button", { name: "Expand to fullscreen" }),
    );

    const portal = document.getElementById("fullscreen-portal");
    expect(portal).not.toBeNull();
    expect(portal).toHaveTextContent("Test plan");
    expect(
      within(portal as HTMLElement).getByRole("button", {
        name: "Exit fullscreen",
      }),
    ).toBeInTheDocument();
  });

  it("exits fullscreen when Escape is pressed", async () => {
    const user = userEvent.setup();
    renderPlanSession();

    await user.click(
      screen.getByRole("button", { name: "Expand to fullscreen" }),
    );
    fireEvent.keyDown(window, { key: "Escape" });

    expect(
      screen.getByRole("button", { name: "Expand to fullscreen" }),
    ).toBeInTheDocument();
  });
});
