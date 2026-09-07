import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ModelSwitchCacheDialog } from "./ModelSwitchCacheDialog";

const taskUsageState = vi.hoisted(() => ({
  data: undefined as
    | {
        token_cost_usd: number;
        compute_cost_usd: number;
        total_cost_usd: number;
      }
    | undefined,
}));
vi.mock("@posthog/ui/features/sessions/hooks/useTaskUsage", () => ({
  useTaskUsage: () => taskUsageState,
}));

describe("ModelSwitchCacheDialog", () => {
  beforeEach(() => {
    useSettingsStore.setState({ warnOnMidSessionModelSwitch: true });
    taskUsageState.data = undefined;
  });

  it("shows the same task cost used by the context indicator", () => {
    taskUsageState.data = {
      token_cost_usd: 12.5,
      compute_cost_usd: 0.4,
      total_cost_usd: 12.9,
    };

    render(
      <ModelSwitchCacheDialog
        open
        fromModelLabel="Claude Sonnet 5"
        toModelId="claude-opus-5"
        toModelLabel="Claude Opus 5"
        taskId="task-1"
        onConfirm={vi.fn().mockResolvedValue(true)}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText("Estimated task cost so far")).toBeInTheDocument();
    expect(screen.getByText("$12.90")).toBeInTheDocument();
  });

  it("keeps future warnings enabled when the user selects do not show again and cancels", () => {
    const onCancel = vi.fn();
    render(
      <ModelSwitchCacheDialog
        open
        fromModelLabel="Claude Sonnet 5"
        toModelId="claude-opus-5"
        toModelLabel="Claude Opus 5"
        onConfirm={vi.fn().mockResolvedValue(undefined)}
        onCancel={onCancel}
      />,
    );

    fireEvent.click(screen.getByText("Do not show this ever again"));
    fireEvent.click(screen.getByText("Cancel"));

    expect(onCancel).toHaveBeenCalledOnce();
    expect(useSettingsStore.getState().warnOnMidSessionModelSwitch).toBe(true);
  });

  it("does not inherit a prior action's busy state when reopened for a new switch", () => {
    const onConfirm = vi.fn().mockReturnValue(new Promise<void>(() => {}));
    const onCancel = vi.fn();
    const props = {
      fromModelLabel: "Claude Sonnet 5",
      toModelId: "claude-opus-5",
      toModelLabel: "Claude Opus 5",
      onConfirm,
      onCancel,
    };
    const { rerender } = render(<ModelSwitchCacheDialog open {...props} />);

    fireEvent.click(screen.getByText("Switch now"));
    rerender(<ModelSwitchCacheDialog open={false} {...props} />);
    rerender(<ModelSwitchCacheDialog open {...props} />);

    fireEvent.click(screen.getByText("Cancel"));
    expect(onCancel).toHaveBeenCalledOnce();
  });
});
