import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

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

function renderSelector() {
  return render(
    <Theme>
      <TaskSelector
        cellIndex={0}
        open
        onOpenChange={() => {}}
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
  it("keeps the task popup wider than its compact trigger", () => {
    renderSelector();

    expectPopupWidth(screen.getByPlaceholderText("Search tasks..."));
  });

  it("keeps the folder popup wide after switching steps", async () => {
    renderSelector();

    await userEvent.click(screen.getByRole("button", { name: "Terminal" }));

    expectPopupWidth(screen.getByPlaceholderText("Search folders..."));
  });
});
