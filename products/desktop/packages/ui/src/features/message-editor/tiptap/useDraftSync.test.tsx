import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/shell/rendererStorage", () => ({
  electronStorage: {
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  },
}));

import { useDraftStore } from "@posthog/ui/features/message-editor/draftStore";
import { Editor } from "@tiptap/core";
import { getEditorExtensions } from "./extensions";
import { useDraftSync } from "./useDraftSync";

// A real editor rather than a stub of the commands the hook calls: what the
// restore path is worth testing for is the text a user would see in the box.
function makeEditor(): Editor {
  const element = document.createElement("div");
  document.body.appendChild(element);
  return new Editor({
    element,
    extensions: getEditorExtensions({ sessionId: "session-1" }),
  });
}

function DraftAttachmentsProbe({ sessionId }: { sessionId: string }) {
  const { restoredAttachments } = useDraftSync(null, sessionId);
  return (
    <div>
      {restoredAttachments.map((att) => att.label).join(",") || "empty"}
    </div>
  );
}

function RestoreProbe({
  editor,
  sessionId,
  initialContent,
}: {
  editor: Editor;
  sessionId: string;
  initialContent?: string;
}) {
  useDraftSync(editor, sessionId, undefined, initialContent);
  return null;
}

describe("useDraftSync", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useDraftStore.setState((state) => ({
      ...state,
      drafts: {},
      contexts: {},
      commands: {},
      focusRequested: {},
      pendingContent: {},
      _hasHydrated: true,
    }));
  });

  // The composer is what a user sees on open, and two things want to fill it.
  it.each([
    [
      "starts from initialContent when the session has no draft",
      null,
      "Sales by week",
    ],
    [
      "leaves a saved draft alone",
      { segments: [{ type: "text" as const, text: "half a thought" }] },
      "half a thought",
    ],
  ])("%s", (_name, draft, expected) => {
    const editor = makeEditor();
    if (draft) {
      useDraftStore.getState().actions.setDraft("session-restore", draft);
    }

    render(
      <RestoreProbe
        editor={editor}
        sessionId="session-restore"
        initialContent="Sales by week"
      />,
    );

    expect(editor.getText()).toBe(expected);
  });

  // Drafts land only once the store hydrates, so filling the box before that
  // would show the caller's text and then swap it for what the user had typed.
  it("holds initialContent until the draft store hydrates", () => {
    useDraftStore.setState((state) => ({ ...state, _hasHydrated: false }));
    const editor = makeEditor();

    render(
      <RestoreProbe
        editor={editor}
        sessionId="session-hydration"
        initialContent="Sales by week"
      />,
    );
    expect(editor.getText()).toBe("");

    act(() => {
      useDraftStore.getState().actions.setHasHydrated(true);
    });
    expect(editor.getText()).toBe("Sales by week");
  });

  it("clears restored attachments when a draft no longer has attachments", () => {
    const { rerender } = render(
      <DraftAttachmentsProbe sessionId="session-1" />,
    );

    act(() => {
      useDraftStore.getState().actions.setDraft("session-1", {
        segments: [{ type: "text", text: "hello" }],
        attachments: [{ id: "/tmp/file.txt", label: "file.txt" }],
      });
    });

    expect(screen.getByText("file.txt")).toBeInTheDocument();

    act(() => {
      useDraftStore.getState().actions.setDraft("session-1", {
        segments: [{ type: "text", text: "hello" }],
      });
    });

    expect(screen.getByText("empty")).toBeInTheDocument();

    rerender(<DraftAttachmentsProbe sessionId="session-2" />);
    expect(screen.getByText("empty")).toBeInTheDocument();
  });
});
