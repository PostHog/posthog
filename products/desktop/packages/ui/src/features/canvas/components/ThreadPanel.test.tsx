import { useReviewNavigationStore } from "@posthog/ui/features/code-review/reviewNavigationStore";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  AgentStatusLine,
  ThreadArtifactRow,
  ThreadMessageRow,
} from "./ThreadPanel";

const openExternalUrl = vi.fn();
const navigateToShareTarget = vi.fn();
let postHogOrigin = "https://us.posthog.com";

vi.mock("@posthog/ui/shell/openExternal", () => ({
  openExternalUrl: (url: string) => openExternalUrl(url),
}));

vi.mock("@posthog/ui/utils/shareLinks", () => ({
  navigateToShareTarget: (target: unknown) => navigateToShareTarget(target),
}));

vi.mock("@posthog/ui/utils/urls", () => ({
  getPostHogUrl: (path: string) => `${postHogOrigin}${path}`,
}));

vi.mock("@posthog/ui/features/git-interaction/usePrDetails", () => ({
  usePrDetails: () => ({
    meta: { state: "open", merged: false, draft: false },
  }),
}));

beforeEach(() => {
  openExternalUrl.mockClear();
  navigateToShareTarget.mockClear();
  postHogOrigin = "https://us.posthog.com";
});

describe("AgentStatusLine", () => {
  it("renders working status outside the conversation timeline", () => {
    render(<AgentStatusLine status={{ phase: "active", label: "Working…" }} />);

    const status = screen.getByText("Working…");

    expect(status.closest("article")).toBeNull();
    expect(status.closest('[data-slot="thread-item-body"]')).toBeNull();
    expect(status.closest("output")).not.toBeNull();
  });
});

describe("ThreadMessageRow", () => {
  it("keeps legacy authorless rows as human messages", () => {
    render(
      <ThreadMessageRow
        message={{
          id: "legacy-message",
          task: "task",
          content: "Author removed",
          created_at: "2026-07-17T00:00:00Z",
          author: null,
        }}
        isTaskAuthor
        isOwnMessage={false}
        canForward
        onSendToAgent={() => {}}
        onDelete={() => {}}
      />,
    );

    expect(screen.getByText("Unknown")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Message actions" }),
    ).toBeInTheDocument();
  });

  const multiline = "First line\n\nSecond line with more detail";

  it("renders the whole message, so a comment is never cut short", () => {
    render(
      <ThreadMessageRow
        message={{
          id: "m1",
          task: "task",
          content: multiline,
          created_at: "2026-07-17T00:00:00Z",
          author: null,
        }}
        isTaskAuthor
        isOwnMessage={false}
        canForward
        onSendToAgent={() => {}}
        onDelete={() => {}}
      />,
    );

    expect(
      screen.getByText(/Second line with more detail/),
    ).toBeInTheDocument();
  });

  it("shows the full message in timeline previews", () => {
    render(
      <ThreadMessageRow
        message={{
          id: "m1",
          task: "task",
          content: multiline,
          created_at: "2026-07-17T00:00:00Z",
          author: null,
        }}
        isTaskAuthor
        isOwnMessage={false}
        canForward
        preview
        onSendToAgent={() => {}}
        onDelete={() => {}}
      />,
    );

    const body = screen.getByText(/Second line with more detail/).parentElement;
    expect(body).toHaveClass("whitespace-pre-wrap", "break-words");
    expect(body).not.toHaveClass("line-clamp-1");
  });
});

describe("ThreadArtifactRow", () => {
  it("opens a canvas from the local development instance", () => {
    postHogOrigin = "http://localhost:8010";
    render(
      <ThreadArtifactRow
        artifact={{
          kind: "canvas",
          name: "Local canvas",
          url: "http://localhost:8010/code/canvas/channel-1/dash-1",
        }}
        createdAt="2026-07-17T00:00:00Z"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Local canvas/ }));

    expect(navigateToShareTarget).toHaveBeenCalledWith({
      kind: "canvas",
      channelId: "channel-1",
      dashboardId: "dash-1",
    });
  });

  it("renders a canvas artifact and navigates in-app to a shareable canvas", () => {
    render(
      <ThreadArtifactRow
        artifact={{
          kind: "canvas",
          name: "Signups overview",
          url: "https://us.posthog.com/code/canvas/channel-1/dash-1",
        }}
        createdAt="2026-07-17T00:00:00Z"
        openInPlaceTaskId="task-1"
      />,
    );

    expect(screen.getByText("Signups overview")).toBeInTheDocument();
    expect(screen.getByText(/Canvas/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Signups overview/ }));

    expect(navigateToShareTarget).toHaveBeenCalledWith({
      kind: "canvas",
      channelId: "channel-1",
      dashboardId: "dash-1",
    });
    expect(openExternalUrl).not.toHaveBeenCalled();
  });

  it("renders a canvas artifact without a link as plain text", () => {
    render(
      <ThreadArtifactRow
        artifact={{ kind: "canvas", name: "Signups overview", url: null }}
        createdAt="2026-07-17T00:00:00Z"
        openInPlaceTaskId="task-1"
      />,
    );

    expect(screen.getByText("Signups overview")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Signups overview/ }),
    ).not.toBeInTheDocument();
  });

  it("opens a canvas from another PostHog instance externally", () => {
    const url = "https://eu.posthog.com/code/canvas/channel-1/dash-1";

    render(
      <ThreadArtifactRow
        artifact={{ kind: "canvas", name: "Signups overview", url }}
        createdAt="2026-07-17T00:00:00Z"
        openInPlaceTaskId="task-1"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Signups overview/ }));

    expect(openExternalUrl).toHaveBeenCalledWith(url);
    expect(navigateToShareTarget).not.toHaveBeenCalled();
  });

  it("opens a pull request in the review pane, and on GitHub from its own button", () => {
    const url = "https://github.com/org/repo/pull/123";

    render(
      <ThreadArtifactRow
        artifact={{ kind: "pr", url }}
        createdAt="2026-07-17T00:00:00Z"
        openInPlaceTaskId="task-1"
      />,
    );

    expect(screen.getByText("Pull request #123")).toBeInTheDocument();

    // The card's own name leads with the title; the GitHub button's trails it.
    fireEvent.click(screen.getByRole("button", { name: /^Pull request #123/ }));

    const review = useReviewNavigationStore.getState();
    expect(review.selectedPrUrls["task-1"]).toBe(url);
    expect(review.reviewModes["task-1"]).toBe("split");
    expect(openExternalUrl).not.toHaveBeenCalled();

    fireEvent.click(
      screen.getByRole("button", { name: "Open Pull request #123 externally" }),
    );

    expect(openExternalUrl).toHaveBeenCalledWith(url);
    expect(navigateToShareTarget).not.toHaveBeenCalled();
  });

  it.each([
    [
      "canvas",
      { kind: "canvas", name: "Unsafe canvas", url: "file:///tmp/canvas" },
      "Unsafe canvas",
    ],
    [
      "pull request",
      { kind: "pr", url: "javascript:alert(1)" },
      "Pull request",
    ],
  ] as const)(
    "renders an unsafe %s artifact without a link",
    (_, artifact, title) => {
      render(
        <ThreadArtifactRow
          artifact={artifact}
          createdAt="2026-07-17T00:00:00Z"
          openInPlaceTaskId="task-1"
        />,
      );

      expect(screen.getAllByText(title).length).toBeGreaterThan(0);
      expect(
        screen.queryByRole("button", { name: new RegExp(title) }),
      ).toBeNull();
    },
  );

  it.each([
    [
      "canvas",
      {
        kind: "canvas",
        name: "Spoofed canvas",
        url: "https://posthog.com.attacker.example/code/canvas/channel-1/dash-1",
      },
      "Spoofed canvas",
    ],
    [
      "pull request",
      {
        kind: "pr",
        url: "https://github.com.attacker.example/org/repo/pull/123",
      },
      "Pull request",
    ],
  ] as const)(
    "renders a %s artifact from a lookalike host without a link",
    (_, artifact, title) => {
      render(
        <ThreadArtifactRow
          artifact={artifact}
          createdAt="2026-07-17T00:00:00Z"
          openInPlaceTaskId="task-1"
        />,
      );

      expect(screen.getAllByText(title).length).toBeGreaterThan(0);
      expect(
        screen.queryByRole("button", { name: new RegExp(title) }),
      ).toBeNull();
    },
  );
});
