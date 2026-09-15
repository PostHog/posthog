import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

const onNewTask = vi.fn();

function renderSelector() {
  return render(
    <Theme>
      <TaskSelector
        cellIndex={0}
        open
        onOpenChange={() => {}}
        onNewTask={onNewTask}
        onNewTerminal={() => {}}
      >
        <button type="button">Add task</button>
      </TaskSelector>
    </Theme>,
  );
}

function expectPopupWidth(input: HTMLElement) {
  expect(input.closest(".combobox-content")).toHaveStyle({
    minWidth: "240px",
  });
}

describe("TaskSelector", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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

  // Routing this to the full-page composer navigates the whole grid away.
  it("composes a new task in the tile rather than navigating", async () => {
    renderSelector();

    await userEvent.click(screen.getByRole("button", { name: "New task" }));

    expect(onNewTask).toHaveBeenCalledOnce();
  });
});
