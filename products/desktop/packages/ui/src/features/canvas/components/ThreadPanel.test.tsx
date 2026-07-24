import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  AgentStatusLine,
  ThreadArtifactRow,
  ThreadMessageRow,
} from "./ThreadPanel";

const openExternalUrl = vi.fn();
const navigateToShareTarget = vi.fn();

vi.mock("@posthog/ui/shell/openExternal", () => ({
  openExternalUrl: (url: string) => openExternalUrl(url),
}));

vi.mock("@posthog/ui/utils/shareLinks", () => ({
  navigateToShareTarget: (target: unknown) => navigateToShareTarget(target),
}));

vi.mock("@posthog/ui/utils/urls", () => ({
  getPostHogUrl: (path: string) => `https://us.posthog.com${path}`,
}));

vi.mock("@posthog/ui/features/git-interaction/usePrDetails", () => ({
  usePrDetails: () => ({
    meta: { state: "open", merged: false, draft: false },
  }),
}));

beforeEach(() => {
  openExternalUrl.mockClear();
  navigateToShareTarget.mockClear();
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
});

describe("ThreadArtifactRow", () => {
  it("renders a canvas artifact and navigates in-app to a shareable canvas", () => {
    render(
      <ThreadArtifactRow
        artifact={{
          kind: "canvas",
          name: "Signups overview",
          url: "https://us.posthog.com/code/canvas/channel-1/dash-1",
        }}
        createdAt="2026-07-17T00:00:00Z"
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
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Signups overview/ }));

    expect(openExternalUrl).toHaveBeenCalledWith(url);
    expect(navigateToShareTarget).not.toHaveBeenCalled();
  });

  it("renders a pull request artifact and opens it externally", () => {
    render(
      <ThreadArtifactRow
        artifact={{ kind: "pr", url: "https://github.com/org/repo/pull/123" }}
        createdAt="2026-07-17T00:00:00Z"
      />,
    );

    expect(screen.getByText("Pull request #123")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Pull request #123/ }));

    expect(openExternalUrl).toHaveBeenCalledWith(
      "https://github.com/org/repo/pull/123",
    );
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
        />,
      );

      expect(screen.getAllByText(title).length).toBeGreaterThan(0);
      expect(
        screen.queryByRole("button", { name: new RegExp(title) }),
      ).toBeNull();
    },
  );
});
