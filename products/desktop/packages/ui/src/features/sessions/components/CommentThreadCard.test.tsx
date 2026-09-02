import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import {
  githubCommentComponents,
  isGitHubHostedImage,
} from "../../editor/components/githubCommentImages";
import { MarkdownRenderer } from "../../editor/components/MarkdownRenderer";
import { CommentThreadCard } from "./CommentThreadCard";

describe("CommentThreadCard", () => {
  it.each([
    "https://user-images.githubusercontent.com/1/example.png",
    "https://private-user-images.githubusercontent.com/1/example.png",
    "https://github.com/user-attachments/assets/12345678-1234-1234-1234-123456789abc",
  ])("allows GitHub-hosted image %s", (source) => {
    expect(isGitHubHostedImage(source)).toBe(true);
  });

  it.each([
    "http://user-images.githubusercontent.com/1/example.png",
    "https://github.com.example.com/user-attachments/assets/example",
    "https://example.com/tracking.png",
    "http://127.0.0.1/internal.png",
    "data:image/png;base64,aW1hZ2U=",
  ])("blocks non-GitHub image %s", (source) => {
    expect(isGitHubHostedImage(source)).toBe(false);
  });

  it("renders only GitHub-hosted images from comment markdown", () => {
    const html = renderToStaticMarkup(
      <MarkdownRenderer
        content={[
          "![GitHub image](https://user-images.githubusercontent.com/1/example.png)",
          "![External image](https://example.com/tracking.png)",
        ].join("\n\n")}
        componentsOverride={githubCommentComponents}
      />,
    );

    expect(html).toContain("user-images.githubusercontent.com/1/example.png");
    expect(html).not.toContain("example.com/tracking.png");
  });

  it("handles a rejected asynchronous resolve action", async () => {
    const onResolve = vi.fn().mockRejectedValue(new Error("unavailable"));
    render(
      <CommentThreadCard
        threadId="thread-1"
        entries={[
          {
            id: "comment-1",
            authorName: "Reviewer",
            user: null,
            avatarUrl: null,
            createdAt: "2026-08-07T00:00:00Z",
            body: "Please update this",
            format: "mentions",
          },
        ]}
        selected={false}
        pulsing={false}
        resolved={false}
        members={[]}
        busy={false}
        onSelect={vi.fn()}
        onReply={vi.fn()}
        onResolve={onResolve}
      />,
    );

    fireEvent.click(screen.getByText("Resolve"));

    await waitFor(() => expect(onResolve).toHaveBeenCalledWith(true));
  });

  it("selects the thread when a reply is clicked", () => {
    const onSelect = vi.fn();
    render(
      <CommentThreadCard
        threadId="thread-1"
        entries={[
          {
            id: "comment-1",
            authorName: "Reviewer",
            user: null,
            avatarUrl: null,
            createdAt: "2026-08-07T00:00:00Z",
            body: "Root comment",
            format: "mentions",
          },
          {
            id: "comment-2",
            authorName: "Author",
            user: null,
            avatarUrl: null,
            createdAt: "2026-08-07T00:01:00Z",
            body: "Reply text",
            format: "mentions",
          },
        ]}
        selected={false}
        pulsing={false}
        resolved={false}
        members={[]}
        busy={false}
        onSelect={onSelect}
        onReply={vi.fn()}
        onResolve={vi.fn()}
      />,
    );

    const selectThread = screen.getByLabelText("Open comment thread");
    expect(selectThread.parentElement).toContainElement(
      screen.getByText("Reply text"),
    );
    fireEvent.click(selectThread);

    expect(onSelect).toHaveBeenCalledOnce();
  });
});
