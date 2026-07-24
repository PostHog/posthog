import type { EditorContent } from "@posthog/core/message-editor/content";
import type { QueuedMessage } from "@posthog/ui/features/sessions/sessionStore";
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/shell/rendererStorage", () => ({
  electronStorage: {
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  },
}));

const sessionService = vi.hoisted(() => ({
  setEditingQueuedMessage: vi.fn(),
  clearEditingQueuedMessage: vi.fn(),
}));

vi.mock("@posthog/core/sessions/sessionService", () => ({
  SESSION_SERVICE: Symbol.for("test.session-service"),
}));

vi.mock("@posthog/di/react", () => ({
  useService: () => sessionService,
}));

const cloudState = vi.hoisted(() => ({ isCloud: false }));
vi.mock("@posthog/ui/features/sessions/sessionStore", () => ({
  useSessionIsCloud: () => cloudState.isCloud,
}));

import { useDraftStore } from "@posthog/ui/features/message-editor/draftStore";
import {
  useCancelQueuedMessageEdit,
  useEditQueuedMessage,
} from "./useEditQueuedMessage";

const TASK = "task-1";

function pendingFor(sessionId: string): EditorContent | undefined {
  return useDraftStore.getState().pendingContent[sessionId];
}
function textContent(text: string): EditorContent {
  return { segments: [{ type: "text", text }] };
}

const QUEUED: QueuedMessage = {
  id: "q-1",
  content: "queued body",
  queuedAt: 1,
};

describe("useEditQueuedMessage / useCancelQueuedMessageEdit", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    cloudState.isCloud = false;
    useDraftStore.setState((state) => ({
      ...state,
      drafts: {},
      pendingContent: {},
      preEditDraft: {},
      _hasHydrated: true,
    }));
  });

  it("restores the pre-edit draft when the edit is cancelled", () => {
    // The user already had a draft typed before clicking Edit.
    act(() => {
      useDraftStore.getState().actions.setDraft(TASK, textContent("my draft"));
    });

    const { result: edit } = renderHook(() => useEditQueuedMessage(TASK));
    const { result: cancel } = renderHook(() =>
      useCancelQueuedMessageEdit(TASK),
    );

    act(() => edit.current(QUEUED));

    // Editing loads the queued message into the composer.
    expect(sessionService.setEditingQueuedMessage).toHaveBeenCalledWith(
      TASK,
      "q-1",
    );
    expect(pendingFor(TASK)?.segments).toEqual([
      { type: "text", text: "queued body" },
    ]);

    act(() => cancel.current());

    // Cancel restores the draft the user had, not empty content.
    expect(sessionService.clearEditingQueuedMessage).toHaveBeenCalledWith(TASK);
    expect(pendingFor(TASK)).toEqual(textContent("my draft"));
  });

  it("clears the composer on cancel when there was no prior draft", () => {
    const { result: edit } = renderHook(() => useEditQueuedMessage(TASK));
    const { result: cancel } = renderHook(() =>
      useCancelQueuedMessageEdit(TASK),
    );

    act(() => edit.current(QUEUED));
    act(() => cancel.current());

    expect(pendingFor(TASK)).toEqual({ segments: [] });
  });

  it("does not treat a whitespace-only draft as restorable", () => {
    act(() => {
      useDraftStore.getState().actions.setDraft(TASK, textContent("   "));
    });

    const { result: edit } = renderHook(() => useEditQueuedMessage(TASK));
    const { result: cancel } = renderHook(() =>
      useCancelQueuedMessageEdit(TASK),
    );

    act(() => edit.current(QUEUED));
    act(() => cancel.current());

    expect(pendingFor(TASK)).toEqual({ segments: [] });
  });

  it.each([
    { variant: "local", isCloud: false, message: QUEUED },
    {
      variant: "cloud",
      isCloud: true,
      message: {
        id: "q-1",
        content: "queued body",
        rawPrompt: [{ type: "text" as const, text: "queued body" }],
        queuedAt: 1,
      },
    },
  ])(
    "loads a $variant queued message into the composer and marks it as the edit target",
    ({ isCloud, message }) => {
      cloudState.isCloud = isCloud;

      const { result: edit } = renderHook(() => useEditQueuedMessage(TASK));
      act(() => edit.current(message));

      expect(sessionService.setEditingQueuedMessage).toHaveBeenCalledWith(
        TASK,
        "q-1",
      );
      expect(pendingFor(TASK)?.segments).toEqual([
        { type: "text", text: "queued body" },
      ]);
    },
  );

  it("does not start an edit when a cloud message has no loadable content", () => {
    cloudState.isCloud = true;

    const { result: edit } = renderHook(() => useEditQueuedMessage(TASK));
    act(() => edit.current({ id: "q-1", content: "", queuedAt: 1 }));

    expect(sessionService.setEditingQueuedMessage).not.toHaveBeenCalled();
    expect(pendingFor(TASK)).toBeUndefined();
  });

  it("snapshots fresh each edit, so a stale draft is not restored later", () => {
    const { result: edit } = renderHook(() => useEditQueuedMessage(TASK));
    const { result: cancel } = renderHook(() =>
      useCancelQueuedMessageEdit(TASK),
    );

    // First edit with a draft present, then cancel (restores + clears snapshot).
    act(() => {
      useDraftStore.getState().actions.setDraft(TASK, textContent("first"));
    });
    act(() => edit.current(QUEUED));
    act(() => cancel.current());
    expect(pendingFor(TASK)).toEqual(textContent("first"));

    // Second edit with an empty composer must not resurrect the first draft.
    act(() => {
      useDraftStore.getState().actions.setDraft(TASK, null);
    });
    act(() => edit.current(QUEUED));
    act(() => cancel.current());
    expect(pendingFor(TASK)).toEqual({ segments: [] });
  });
});
