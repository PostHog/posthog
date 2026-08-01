import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import type { TaskRunStatus } from "@posthog/shared/domain-types";
import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ChannelItemRow } from "./ChannelItemRow";

const actions = {
  open: () => {},
  togglePin: () => {},
  archive: () => {},
};

function item(overrides: Partial<ChannelItemModel> = {}): ChannelItemModel {
  return {
    key: "task:task-1",
    kind: "task",
    id: "task-1",
    title: "Investigate signup drop-off",
    ts: Date.parse("2026-07-17T12:00:00.000Z"),
    pinned: false,
    rawStatus: null,
    authorUser: null,
    authorName: null,
    authorUuid: "user-uuid",
    templateId: null,
    ...overrides,
  };
}

function renderRow(model: ChannelItemModel) {
  return render(
    <Theme>
      <ChannelItemRow actions={actions} isActive={false} item={model} />
    </Theme>,
  );
}

describe("ChannelItemRow", () => {
  it.each([
    ["queued" as const, true],
    ["in_progress" as const, true],
    ["not_started" as const, false],
    ["completed" as const, false],
    ["failed" as const, false],
    ["cancelled" as const, false],
  ])("marks %s as running: %s", (rawStatus: TaskRunStatus, running) => {
    renderRow(item({ rawStatus }));

    expect(!!screen.queryByRole("img", { name: "Running" })).toBe(running);
  });

  it("leaves a canvas, which has no run to wait on, static", () => {
    renderRow(
      item({
        key: "canvas:canvas-1",
        kind: "canvas",
        id: "canvas-1",
        title: "Web analytics overview",
        templateId: "web-analytics",
      }),
    );

    expect(screen.queryByRole("img", { name: "Running" })).toBeNull();
  });

  // The point of the shimmer over a spinner: a running task still looks like a
  // task, so the list stays scannable by kind while work is in flight.
  it("keeps the item's own glyph while running", () => {
    renderRow(item({ rawStatus: "in_progress" }));

    const running = screen.getByRole("img", { name: "Running" });
    expect(running).toHaveClass("ph-shimmer");
    // The glyph is wrapped, not replaced — no spinner swapped in its place.
    expect(running.querySelector("svg")).not.toBeNull();
  });

  it("opens the task context menu from the row", () => {
    const onContextMenu = vi.fn();

    render(
      <Theme>
        <ChannelItemRow
          actions={actions}
          isActive={false}
          item={item()}
          onContextMenu={onContextMenu}
        />
      </Theme>,
    );

    fireEvent.contextMenu(screen.getByText("Investigate signup drop-off"));

    expect(onContextMenu).toHaveBeenCalledOnce();
  });
});
