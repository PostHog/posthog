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
import type { Editor } from "@tiptap/core";
import { useDraftSync } from "./useDraftSync";

// The hook only reaches the editor through commands, so a stub of those is the
// whole surface a restore test needs.
function fakeEditor(): {
  editor: Editor;
  setContent: ReturnType<typeof vi.fn>;
} {
  const setContent = vi.fn();
  const editor = {
    commands: {
      setContent,
      focus: vi.fn(),
      insertContent: vi.fn(),
    },
    getJSON: () => ({ type: "doc", content: [] }),
  } as unknown as Editor;
  return { editor, setContent };
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

function DraftAttachmentsProbe({ sessionId }: { sessionId: string }) {
  const { restoredAttachments } = useDraftSync(null, sessionId);
  return (
    <div>
      {restoredAttachments.map((att) => att.label).join(",") || "empty"}
    </div>
  );
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
      undefined,
    ],
  ])("%s", (_name, draft, expected) => {
    const { editor, setContent } = fakeEditor();
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

    if (expected) {
      expect(setContent).toHaveBeenCalledWith(expected);
    } else {
      expect(setContent).not.toHaveBeenCalledWith("Sales by week");
    }
  });

  // Drafts land only once the store hydrates, so filling the box before that
  // would show the caller's text and then swap it for what the user had typed.
  it("holds initialContent until the draft store hydrates", () => {
    useDraftStore.setState((state) => ({ ...state, _hasHydrated: false }));
    const { editor, setContent } = fakeEditor();

    render(
      <RestoreProbe
        editor={editor}
        sessionId="session-hydration"
        initialContent="Sales by week"
      />,
    );
    expect(setContent).not.toHaveBeenCalled();

    act(() => {
      useDraftStore.getState().actions.setHasHydrated(true);
    });
    expect(setContent).toHaveBeenCalledWith("Sales by week");
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
