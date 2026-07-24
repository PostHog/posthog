import type { PermissionOption } from "@agentclientprotocol/sdk";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { Theme } from "@radix-ui/themes";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PlanApprovalSelector } from "./PlanApprovalSelector";
import type { PermissionToolCall } from "./types";

const AUTO: PermissionOption = {
  kind: "allow_always",
  name: 'Yes, and use "auto" mode',
  optionId: "auto",
};
const ACCEPT_EDITS: PermissionOption = {
  kind: "allow_always",
  name: "Yes, and auto-accept edits",
  optionId: "acceptEdits",
};
const DEFAULT_MODE: PermissionOption = {
  kind: "allow_once",
  name: "Yes, and manually approve edits",
  optionId: "default",
};
const REJECT: PermissionOption = {
  kind: "reject_once",
  name: "No, and tell the agent what to do differently",
  optionId: "reject_with_feedback",
  _meta: { customInput: true },
};

const toolCall = {
  toolCallId: "plan-1",
  title: "Approve this plan to proceed?",
} as PermissionToolCall;

function renderSelector(options: PermissionOption[]) {
  const onSelect = vi.fn();
  const onCancel = vi.fn();
  render(
    <Theme>
      <PlanApprovalSelector
        toolCall={toolCall}
        options={options}
        onSelect={onSelect}
        onCancel={onCancel}
      />
    </Theme>,
  );
  return { onSelect, onCancel };
}

describe("PlanApprovalSelector", () => {
  beforeEach(() => {
    // Reset the remembered choice so tests don't leak through persistence.
    useSettingsStore.setState({ lastPlanApprovalMode: null });
  });

  it.each([
    {
      label: "there is no prior or remembered mode",
      lastMode: null,
      options: [AUTO, ACCEPT_EDITS, DEFAULT_MODE, REJECT],
      expected: "auto",
    },
    {
      label: "a last choice is remembered",
      lastMode: "acceptEdits",
      options: [AUTO, ACCEPT_EDITS, DEFAULT_MODE],
      expected: "acceptEdits",
    },
  ] as const)(
    "defaults to $expected when $label",
    async ({ lastMode, options, expected }) => {
      const user = userEvent.setup();
      useSettingsStore.setState({ lastPlanApprovalMode: lastMode });
      const { onSelect } = renderSelector([...options]);

      await user.click(screen.getByText("Approve and proceed"));

      expect(onSelect).toHaveBeenCalledTimes(1);
      expect(onSelect).toHaveBeenCalledWith(expected);
    },
  );

  it("remembers the chosen mode on approve", async () => {
    const user = userEvent.setup();
    renderSelector([AUTO, ACCEPT_EDITS, DEFAULT_MODE, REJECT]);

    await user.click(screen.getByText("Approve and proceed"));

    expect(useSettingsStore.getState().lastPlanApprovalMode).toBe("auto");
  });

  it("picks up a remembered mode that loads after mount", async () => {
    // Settings persist asynchronously (an IPC round trip on desktop), so the
    // selector can mount before `lastPlanApprovalMode` has loaded from disk.
    const user = userEvent.setup();
    const { onSelect } = renderSelector([AUTO, ACCEPT_EDITS, DEFAULT_MODE]);

    // The remembered choice loads in after mount.
    act(() => {
      useSettingsStore.setState({ lastPlanApprovalMode: "acceptEdits" });
    });

    await user.click(screen.getByText("Approve and proceed"));

    expect(onSelect).toHaveBeenCalledWith("acceptEdits");
  });

  it("does not clobber a mode the user already picked", async () => {
    const user = userEvent.setup();
    const { onSelect } = renderSelector([AUTO, ACCEPT_EDITS, DEFAULT_MODE]);

    await user.click(screen.getByRole("button", { name: "Mode" }));
    await user.click(await screen.findByText("Manually approve edits"));
    // The dropdown applies the pick when its close animation completes, not
    // synchronously with the click, so wait for it to actually land before
    // moving on — otherwise this race decides the test's outcome.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Mode" })).toHaveTextContent(
        "Manually approve edits",
      ),
    );

    // The remembered choice loads in after the user already picked a mode.
    act(() => {
      useSettingsStore.setState({ lastPlanApprovalMode: "acceptEdits" });
    });

    await user.click(screen.getByText("Approve and proceed"));

    expect(onSelect).toHaveBeenCalledWith("default");
  });

  it("drops a manual pick when a later approval request reuses this instance", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const options = [AUTO, ACCEPT_EDITS, DEFAULT_MODE];
    const { rerender } = render(
      <Theme>
        <PlanApprovalSelector
          toolCall={toolCall}
          options={options}
          onSelect={onSelect}
          onCancel={vi.fn()}
        />
      </Theme>,
    );

    await user.click(screen.getByRole("button", { name: "Mode" }));
    await user.click(await screen.findByText("Manually approve edits"));
    // The dropdown applies the pick when its close animation completes, not
    // synchronously with the click — wait for it to land before rerendering,
    // or the pending pick can apply after (and survive) the reset below.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Mode" })).toHaveTextContent(
        "Manually approve edits",
      ),
    );

    // The component isn't guaranteed to unmount between requests; a new
    // toolCallId means a new request even if this instance is reused.
    rerender(
      <Theme>
        <PlanApprovalSelector
          toolCall={{ ...toolCall, toolCallId: "plan-2" } as PermissionToolCall}
          options={options}
          onSelect={onSelect}
          onCancel={vi.fn()}
        />
      </Theme>,
    );

    await user.click(screen.getByText("Approve and proceed"));

    expect(onSelect).toHaveBeenCalledWith("auto");
  });

  it("rejects with the typed feedback", async () => {
    const user = userEvent.setup();
    const { onSelect } = renderSelector([DEFAULT_MODE, REJECT]);

    // Selecting the reject row activates its inline textarea (as before).
    await user.click(screen.getByText("2."));
    await user.type(
      screen.getByPlaceholderText(/tell the agent what to do differently/i),
      "please use hooks{Enter}",
    );

    expect(onSelect).toHaveBeenCalledWith(
      "reject_with_feedback",
      "please use hooks",
    );
  });

  it("does not reject on empty feedback (Enter is a no-op, exactly as before)", async () => {
    const user = userEvent.setup();
    const { onSelect } = renderSelector([DEFAULT_MODE, REJECT]);

    await user.click(screen.getByText("2."));
    await user.type(
      screen.getByPlaceholderText(/tell the agent what to do differently/i),
      "{Enter}",
    );

    expect(onSelect).not.toHaveBeenCalled();
  });

  it("cancels on Escape", async () => {
    const user = userEvent.setup();
    const { onCancel } = renderSelector([DEFAULT_MODE, REJECT]);

    await user.keyboard("{Escape}");

    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
