import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/shell/analytics", () => ({
  track: vi.fn(),
  setActiveTaskContext: vi.fn(),
}));

vi.mock("./ArtifactPreview", () => ({
  ArtifactPreview: ({ name }: { name: string }) => (
    <div data-testid="artifact-preview">{name}</div>
  ),
}));

import { DEFAULT_PANEL_IDS } from "@posthog/core/panels/panelConstants";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { getLeafPanel } from "@posthog/ui/features/panels/panelStoreHelpers";
import { EmbeddedArtifactTabs } from "./EmbeddedArtifactTabs";

describe("EmbeddedArtifactTabs", () => {
  beforeEach(() => {
    usePanelLayoutStore.getState().clearAllLayouts();
    localStorage.clear();
  });

  function renderTabs() {
    return render(
      <EmbeddedArtifactTabs taskId="task-1">
        <div data-testid="session">Chat thread</div>
      </EmbeddedArtifactTabs>,
    );
  }

  function openArtifact(name: string, artifactId: string) {
    act(() => {
      usePanelLayoutStore
        .getState()
        .openArtifactTab("task-1", { runId: "run-1", artifactId, name });
    });
  }

  it("shows the session alone until the task has an artifact tab", () => {
    renderTabs();

    expect(screen.getByTestId("session")).toBeInTheDocument();
    expect(screen.queryByText("Chat")).not.toBeInTheDocument();
    expect(screen.queryByTestId("artifact-preview")).not.toBeInTheDocument();
  });

  // The bug this guards: the tab opened from the chat's Files box lands in the
  // task's layout, and an embedded surface used to render nothing for it.
  it("renders the artifact tab the task's layout holds", () => {
    renderTabs();
    openArtifact("hero.png", "artifact-1");

    expect(screen.getByTestId("artifact-preview")).toHaveTextContent(
      "hero.png",
    );
    expect(screen.getByText("Chat")).toBeInTheDocument();
  });

  it("goes back to the session from the chat tab", () => {
    renderTabs();
    openArtifact("hero.png", "artifact-1");

    fireEvent.click(screen.getByText("Chat"));

    expect(screen.queryByTestId("artifact-preview")).not.toBeInTheDocument();
    expect(screen.getByTestId("session")).toBeInTheDocument();
  });

  it("drops the tab from the task's layout when it is closed", () => {
    renderTabs();
    openArtifact("hero.png", "artifact-1");

    fireEvent.click(screen.getByLabelText("Close hero.png"));

    expect(screen.queryByTestId("artifact-preview")).not.toBeInTheDocument();
    expect(screen.queryByText("hero.png")).not.toBeInTheDocument();
    const layout = usePanelLayoutStore.getState().getLayout("task-1");
    const panel = layout
      ? getLeafPanel(layout.panelTree, DEFAULT_PANEL_IDS.MAIN_PANEL)
      : null;
    expect(panel?.content.tabs.map((tab) => tab.id)).not.toContain(
      "artifact-artifact-1",
    );
  });
});
