import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { PanelContent } from "../panelTypes";

const panelDropZonesSpy = vi.hoisted(() =>
  vi.fn((_props: { allowSplit?: boolean }) => null),
);

vi.mock("@dnd-kit/react", () => ({
  useDroppable: () => ({ ref: vi.fn() }),
}));

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPCClient: () => ({
    contextMenu: {
      showSplitContextMenu: { mutate: vi.fn() },
    },
  }),
}));

vi.mock("./PanelDropZones", () => ({
  PanelDropZones: panelDropZonesSpy,
}));

vi.mock("./PanelTab", () => ({
  PanelTab: ({ label, onSelect }: { label: string; onSelect: () => void }) => (
    <button type="button" onClick={onSelect}>
      {label}
    </button>
  ),
}));

import { TabbedPanel } from "./TabbedPanel";

function content(activeTabId: string): PanelContent {
  return {
    id: "main",
    activeTabId,
    showTabs: false,
    tabs: [
      {
        id: "logs",
        label: "Logs",
        data: { type: "logs" },
        component: <div data-testid="logs-content" />,
      },
      {
        id: "review",
        label: "Review",
        data: { type: "review" },
        component: <div data-testid="review-content" />,
      },
    ],
  };
}

describe("TabbedPanel", () => {
  it("disables split drop zones when panel splitting is unavailable", () => {
    const droppableContent = { ...content("logs"), droppable: true };

    render(
      <Theme>
        <TabbedPanel
          panelId="main"
          mountScopeKey="task-a"
          content={droppableContent}
          draggingTabId="logs"
          allowPanelSplit={false}
        />
      </Theme>,
    );

    expect(panelDropZonesSpy.mock.lastCall?.[0]).toEqual(
      expect.objectContaining({ allowSplit: false }),
    );
  });

  it("retains visited tabs within a task and resets them for another task", () => {
    const { rerender } = render(
      <Theme>
        <TabbedPanel
          panelId="main"
          mountScopeKey="task-a"
          content={content("logs")}
        />
      </Theme>,
    );

    expect(screen.getByTestId("logs-content")).toBeInTheDocument();
    expect(screen.queryByTestId("review-content")).not.toBeInTheDocument();

    rerender(
      <Theme>
        <TabbedPanel
          panelId="main"
          mountScopeKey="task-a"
          content={content("review")}
        />
      </Theme>,
    );

    expect(screen.getByTestId("logs-content")).toBeInTheDocument();
    expect(screen.getByTestId("review-content")).toBeInTheDocument();

    rerender(
      <Theme>
        <TabbedPanel
          panelId="main"
          mountScopeKey="task-b"
          content={content("logs")}
        />
      </Theme>,
    );

    expect(screen.getByTestId("logs-content")).toBeInTheDocument();
    expect(screen.queryByTestId("review-content")).not.toBeInTheDocument();
  });
});
