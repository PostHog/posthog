import type { Task } from "@posthog/shared/domain-types";
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { LeafPanel } from "../panelTypes";

vi.mock("../../../shell/useHostCapabilities", () => ({
  useHostCapabilities: () => ({ localWorkspaces: false }),
}));

vi.mock("../../workspace/useWorkspace", () => ({
  useIsCloudTask: () => false,
}));

vi.mock("../hooks/usePanelLayoutHooks", () => ({
  useTabInjection: (tabs: unknown) => tabs,
}));

vi.mock("./TabbedPanel", () => ({
  TabbedPanel: () => null,
}));

import { LeafNodeRenderer } from "./LeafNodeRenderer";

function leaf(activeTabId: string): LeafPanel {
  return {
    type: "leaf",
    id: "main-panel",
    content: {
      id: "main-panel",
      activeTabId,
      tabs: [
        { id: "logs", label: "Chat", data: { type: "logs" }, closeable: false },
        {
          id: "shell",
          label: "Terminal",
          data: { type: "terminal", terminalId: "shell", cwd: "" },
        },
      ],
    },
  };
}

describe("LeafNodeRenderer", () => {
  it.each([
    ["shell", [["main-panel", "logs"]]],
    ["logs", []],
  ])(
    "moves a stored active tab of %s onto the visible tab when terminals are hidden",
    (activeTabId, expectedCalls) => {
      const onActiveTabChange = vi.fn();

      render(
        <LeafNodeRenderer
          node={leaf(activeTabId)}
          taskId="task-1"
          task={{} as Task}
          closeTab={vi.fn()}
          closeOtherTabs={vi.fn()}
          closeTabsToRight={vi.fn()}
          keepTab={vi.fn()}
          draggingTabId={null}
          draggingTabPanelId={null}
          onActiveTabChange={onActiveTabChange}
          onPanelFocus={vi.fn()}
          onAddTerminal={vi.fn()}
          onSplitPanel={vi.fn()}
          onClosePanel={vi.fn()}
        />,
      );

      expect(onActiveTabChange.mock.calls).toEqual(expectedCalls);
    },
  );
});
