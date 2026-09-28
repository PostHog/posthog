import type { EditorContent } from "@posthog/core/message-editor/content";
import { describe, expect, it, vi } from "vitest";
import {
  type CommentToAgentHost,
  CommentToAgentService,
  commentComposerContent,
} from "./commentToAgent";

function fakeHost(overrides: Partial<CommentToAgentHost> = {}) {
  const inserted: EditorContent[] = [];
  const host: CommentToAgentHost = {
    persistScreenshot: vi.fn(async () => "/tmp/shot.png"),
    getDraft: () => null,
    hasPendingInsert: () => false,
    insertIntoDraft: (_taskId, content) => inserted.push(content),
    showTaskChat: vi.fn(),
    trackCommentSent: vi.fn(),
    ...overrides,
  };
  return { host, inserted };
}

describe("commentToAgent", () => {
  it("puts the context chip before the editable comment", () => {
    expect(
      commentComposerContent({
        comment: "Make this red",
        draftEmpty: false,
        context: { label: 'h1 "Hot stuff"', body: "- **Page** /" },
      }).segments,
    ).toEqual([
      { type: "text", text: "\n" },
      {
        type: "chip",
        chip: {
          type: "comment_context",
          id: "- **Page** /",
          label: 'h1 "Hot stuff"',
        },
      },
      { type: "text", text: " " },
      { type: "text", text: "Make this red" },
    ]);
  });

  it.each([
    { name: "an empty draft", pending: false, startsOnNewLine: false },
    { name: "a queued insert", pending: true, startsOnNewLine: true },
  ])(
    "starts the comment on a new line after $name",
    async ({ pending, startsOnNewLine }) => {
      const { host, inserted } = fakeHost({ hasPendingInsert: () => pending });

      await new CommentToAgentService(host).send({
        taskId: "task-1",
        comment: "Fix it",
        context: null,
        surface: "task",
      });

      expect(inserted[0].segments[0]).toEqual(
        startsOnNewLine
          ? { type: "text", text: "\n" }
          : { type: "text", text: "Fix it" },
      );
    },
  );

  it("adds the comment without an image when the screenshot can't be saved", async () => {
    const { host, inserted } = fakeHost({
      persistScreenshot: vi.fn(async () => {
        throw new Error("disk full");
      }),
    });

    await new CommentToAgentService(host).send({
      taskId: "task-1",
      comment: "Fix it",
      context: { label: "button", body: "- **Page** /", screenshot: "data:" },
      surface: "artifact",
      openChat: false,
    });

    expect(inserted[0].segments[0]).toEqual({
      type: "chip",
      chip: { type: "comment_context", id: "- **Page** /", label: "button" },
    });
    expect(host.showTaskChat).not.toHaveBeenCalled();
    expect(host.trackCommentSent).toHaveBeenCalledWith({
      surface: "artifact",
      with_context: true,
      with_screenshot: false,
    });
  });
});
