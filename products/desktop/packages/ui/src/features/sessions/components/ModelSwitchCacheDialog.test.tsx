import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ModelSwitchCacheDialog } from "./ModelSwitchCacheDialog";

describe("ModelSwitchCacheDialog", () => {
  beforeEach(() => {
    useSettingsStore.setState({ warnOnMidSessionModelSwitch: true });
  });

  it("keeps future warnings enabled when the user selects do not show again and cancels", () => {
    const onCancel = vi.fn();
    render(
      <ModelSwitchCacheDialog
        open
        fromModelId="claude-sonnet-5"
        fromModelLabel="Claude Sonnet 5"
        toModelId="claude-opus-5"
        toModelLabel="Claude Opus 5"
        onConfirm={vi.fn().mockResolvedValue(undefined)}
        onCancel={onCancel}
      />,
    );

    fireEvent.click(screen.getByText("Do not show this again"));
    fireEvent.click(screen.getByText("Cancel"));

    expect(onCancel).toHaveBeenCalledOnce();
    expect(useSettingsStore.getState().warnOnMidSessionModelSwitch).toBe(true);
  });
});
