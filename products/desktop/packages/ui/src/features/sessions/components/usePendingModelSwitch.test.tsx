import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { usePendingModelSwitch } from "./usePendingModelSwitch";

const { trackMock } = vi.hoisted(() => ({ trackMock: vi.fn() }));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: trackMock }));

function modelOption(): SessionConfigOption {
  return {
    type: "select",
    id: "model",
    name: "Model",
    category: "model",
    currentValue: "claude-opus-5",
    options: [
      { name: "Claude Sonnet 5", value: "claude-sonnet-5" },
      { name: "Claude Opus 5", value: "claude-opus-5" },
    ],
  } as unknown as SessionConfigOption;
}

interface Props {
  taskId: string | undefined;
  onApply: (configId: string, value: string) => Promise<boolean>;
  hasConversationStarted: boolean;
}

function setup(
  taskId: string | undefined,
  onApply: Props["onApply"],
  hasConversationStarted = true,
) {
  return renderHook(
    (props: Props) =>
      usePendingModelSwitch({
        taskId: props.taskId,
        sessionModelOption: modelOption(),
        hasConversationStarted: props.hasConversationStarted,
        onApply: props.onApply,
      }),
    {
      initialProps: {
        taskId,
        onApply,
        hasConversationStarted,
      },
    },
  );
}

describe("usePendingModelSwitch", () => {
  beforeEach(() => {
    trackMock.mockClear();
    useSettingsStore.setState({ warnOnMidSessionModelSwitch: true });
  });

  it("queues a mid-session switch and applies it on confirm", async () => {
    const onApply = vi.fn().mockResolvedValue(true);
    const { result } = setup("task-a", onApply);

    let intercepted = false;
    act(() => {
      intercepted = result.current.interceptModelSwitch(
        "model",
        "claude-sonnet-5",
      );
    });
    expect(intercepted).toBe(true);
    expect(result.current.pendingModelSwitch?.value).toBe("claude-sonnet-5");

    await act(() => result.current.confirmModelSwitch());
    expect(onApply).toHaveBeenCalledWith("model", "claude-sonnet-5");
    expect(result.current.pendingModelSwitch).toBeNull();
  });

  it("keeps the dialog open when the switch does not reach the agent", async () => {
    const onApply = vi.fn().mockResolvedValue(false);
    const { result } = setup("task-a", onApply);

    act(() => {
      result.current.interceptModelSwitch("model", "claude-sonnet-5");
    });

    let confirmResult: boolean | undefined;
    await act(async () => {
      confirmResult = await result.current.confirmModelSwitch();
    });

    expect(onApply).toHaveBeenCalledWith("model", "claude-sonnet-5");
    expect(confirmResult).toBe(false);
    expect(result.current.pendingModelSwitch).not.toBeNull();
  });

  it("does not queue a switch before the conversation has started", () => {
    const onApply = vi.fn().mockResolvedValue(true);
    const { result } = setup("task-a", onApply, false);

    let intercepted = true;
    act(() => {
      intercepted = result.current.interceptModelSwitch(
        "model",
        "claude-sonnet-5",
      );
    });
    expect(intercepted).toBe(false);
    expect(result.current.pendingModelSwitch).toBeNull();
    expect(onApply).not.toHaveBeenCalled();
  });

  it("drops the queued switch when the task changes so confirm cannot apply it to another session", async () => {
    const onApply = vi.fn().mockResolvedValue(true);
    const { result, rerender } = setup("task-a", onApply);

    act(() => {
      result.current.interceptModelSwitch("model", "claude-sonnet-5");
    });
    expect(result.current.pendingModelSwitch).not.toBeNull();

    // The view swaps to another task without remounting.
    rerender({
      taskId: "task-b",
      onApply,
      hasConversationStarted: true,
    });
    expect(result.current.pendingModelSwitch).toBeNull();

    await act(() => result.current.confirmModelSwitch());
    expect(onApply).not.toHaveBeenCalled();
  });
});
