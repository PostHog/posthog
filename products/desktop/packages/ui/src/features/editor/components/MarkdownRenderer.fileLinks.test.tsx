import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/shell/analytics", () => ({
  track: vi.fn(),
  setActiveTaskContext: vi.fn(),
}));

const taskId = { current: "task-1" as string | null };
const cwd = { current: "/repo" as string | undefined };

vi.mock("@posthog/ui/features/sessions/useSessionTaskId", () => ({
  useSessionTaskId: () => taskId.current,
}));
vi.mock("@posthog/ui/features/sidebar/useCwd", () => ({
  useCwd: () => cwd.current,
}));

import { track } from "@posthog/ui/shell/analytics";
import { usePanelLayoutStore } from "../../panels/panelLayoutStore";
import { MarkdownRenderer } from "./MarkdownRenderer";

function renderMarkdown(content: string) {
  return render(
    <Theme>
      <MarkdownRenderer content={content} />
    </Theme>,
  );
}

describe("MarkdownRenderer file links", () => {
  beforeEach(() => {
    vi.mocked(track).mockClear();
    taskId.current = "task-1";
    cwd.current = "/repo";
    usePanelLayoutStore.getState().clearAllLayouts();
    usePanelLayoutStore.getState().initializeTask("task-1");
  });

  it("opens a repo-relative href in a panel instead of the browser", () => {
    renderMarkdown("See [the renderer](src/App.tsx:79).");

    fireEvent.click(screen.getByRole("button", { name: "the renderer" }));

    expect(
      usePanelLayoutStore.getState().getLayout("task-1")?.openFiles,
    ).toContain("src/App.tsx");
    expect(track).toHaveBeenCalledWith(
      "File opened",
      expect.objectContaining({ source: "markdown-link" }),
    );
  });

  it("relativizes an absolute href against the task's working directory", () => {
    renderMarkdown("See [the renderer](file:///repo/src/App.tsx).");

    fireEvent.click(screen.getByRole("button", { name: "the renderer" }));

    expect(
      usePanelLayoutStore.getState().getLayout("task-1")?.openFiles,
    ).toContain("src/App.tsx");
  });

  it("leaves a web href as an external link", () => {
    renderMarkdown("See [the docs](https://posthog.com/docs).");

    expect(screen.getByRole("link", { name: /the docs/ })).toHaveAttribute(
      "href",
      "https://posthog.com/docs",
    );
  });

  it("renders plain text when no task is in scope", () => {
    taskId.current = null;
    const { container } = renderMarkdown("See [the renderer](src/App.tsx).");

    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
    expect(container.textContent).toBe("See the renderer.");
  });

  it("renders plain text when the task has no working directory", () => {
    cwd.current = undefined;
    renderMarkdown("See [the renderer](src/App.tsx).");

    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
  });
});
