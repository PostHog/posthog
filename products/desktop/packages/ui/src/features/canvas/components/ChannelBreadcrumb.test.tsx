import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => vi.fn(),
}));

import { ChannelBreadcrumb } from "./ChannelBreadcrumb";

describe("ChannelBreadcrumb", () => {
  it("closes title editing when the editable leaf changes", () => {
    const onRename = vi.fn();
    const { rerender } = render(
      <Theme>
        <ChannelBreadcrumb
          channelName="Team"
          leafLabel="Task A"
          editScopeKey="task-a"
          onRename={onRename}
        />
      </Theme>,
    );

    fireEvent.doubleClick(screen.getByText("Task A"));
    expect(screen.getByRole("textbox")).toHaveValue("Task A");

    rerender(
      <Theme>
        <ChannelBreadcrumb
          channelName="Team"
          leafLabel="Task B"
          editScopeKey="task-b"
          onRename={onRename}
        />
      </Theme>,
    );

    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.getByText("Task B")).toBeInTheDocument();
    expect(onRename).not.toHaveBeenCalled();
  });
});
