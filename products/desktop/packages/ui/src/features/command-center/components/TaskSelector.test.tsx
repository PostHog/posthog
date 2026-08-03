import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/features/command-center/hooks/useAvailableTasks", () => ({
  useAvailableTasks: () => [],
}));

vi.mock("@posthog/ui/features/folders/useFolders", () => ({
  useFolders: () => ({
    getRecentFolders: () => [
      { id: "folder-1", name: "one", path: "/one" },
      { id: "folder-2", name: "two", path: "/two" },
    ],
  }),
}));

import { TaskSelector } from "./TaskSelector";

// Mirrors how CommandCenterPanel drives the selector: `open` is real state, so
// the popup can actually unmount when a choice closes it.
function ControlledSelector({
  onNewTerminal,
}: {
  onNewTerminal: (cwd?: string) => void;
}) {
  const [open, setOpen] = useState(true);
  return (
    <Theme>
      <TaskSelector
        cellIndex={0}
        open={open}
        onOpenChange={setOpen}
        onNewTerminal={onNewTerminal}
      >
        <button type="button">Add task</button>
      </TaskSelector>
    </Theme>
  );
}

function renderSelector(onNewTerminal: (cwd?: string) => void = () => {}) {
  return render(<ControlledSelector onNewTerminal={onNewTerminal} />);
}

function expectPopupWidth(input: HTMLElement) {
  expect(input.closest(".combobox-content")).toHaveStyle({
    minWidth: "240px",
  });
}

describe("TaskSelector", () => {
  // Reset before rather than after: an afterEach hook runs ahead of Testing
  // Library's auto-cleanup, so it would update a still-mounted component.
  beforeEach(() => {
    useSettingsStore.setState({ terminalDefaultCwd: "" });
  });

  it("keeps the task popup wider than its compact trigger", () => {
    renderSelector();

    expectPopupWidth(screen.getByPlaceholderText("Search tasks..."));
  });

  it("keeps the folder popup wide after switching steps", async () => {
    renderSelector();

    await userEvent.click(screen.getByRole("button", { name: "Terminal" }));

    expectPopupWidth(screen.getByPlaceholderText("Search folders..."));
  });

  it("opens the default directory instead of prompting for a folder", async () => {
    useSettingsStore.setState({ terminalDefaultCwd: "/default" });
    const onNewTerminal = vi.fn();
    renderSelector(onNewTerminal);

    await userEvent.click(screen.getByRole("button", { name: "Terminal" }));

    expect(onNewTerminal).toHaveBeenCalledWith("/default");
    // The popup closes outright, so neither step is left on screen.
    expect(screen.queryByPlaceholderText("Search folders...")).toBeNull();
    expect(screen.queryByPlaceholderText("Search tasks...")).toBeNull();
  });

  it("still offers an explicit folder choice once a default is set", async () => {
    useSettingsStore.setState({ terminalDefaultCwd: "/default" });
    renderSelector();

    await userEvent.click(screen.getByRole("button", { name: "Terminal in…" }));

    expect(screen.getByPlaceholderText("Search folders...")).toBeVisible();
  });
});
