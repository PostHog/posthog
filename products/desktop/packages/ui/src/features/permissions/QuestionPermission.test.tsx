import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QuestionPermission } from "./QuestionPermission";
import { useQuestionDraftStore } from "./questionDraftStore";
import type { PermissionToolCall } from "./types";

const toolCall = {
  toolCallId: "question-1",
  title: "Questions",
  _meta: {
    codeToolKind: "question",
    questions: [
      {
        question: "Which framework?",
        header: "Framework",
        options: [{ label: "React" }, { label: "Vue" }],
      },
      {
        question: "Which color?",
        header: "Color",
        options: [{ label: "Red" }, { label: "Blue" }],
      },
    ],
  },
} as unknown as PermissionToolCall;

function renderQuestion() {
  const onSelect = vi.fn();
  const onCancel = vi.fn();
  const view = render(
    <Theme>
      <QuestionPermission
        toolCall={toolCall}
        options={[]}
        onSelect={onSelect}
        onCancel={onCancel}
      />
    </Theme>,
  );
  return { onSelect, onCancel, view };
}

describe("QuestionPermission", () => {
  beforeEach(() => {
    useQuestionDraftStore.setState({ drafts: new Map() });
  });

  it("restores in-progress answers when the card remounts", async () => {
    const user = userEvent.setup();
    const first = renderQuestion();

    await user.click(screen.getByText("React"));
    await user.click(screen.getByText("Next"));
    expect(screen.getByText("Which color?")).toBeDefined();

    // Switching chats unmounts the card; the store keeps the draft.
    first.view.unmount();

    const second = renderQuestion();
    expect(screen.getByText("Which color?")).toBeDefined();

    await user.click(screen.getByText("Blue"));
    await user.click(screen.getByText("Next"));

    // The review step summarizes the answer given before the remount.
    expect(screen.getByText("Ready to submit your answers?")).toBeDefined();
    expect(screen.getByText("React")).toBeDefined();

    const submitOptions = screen.getAllByText("Submit");
    await user.click(submitOptions[submitOptions.length - 1] as HTMLElement);

    expect(second.onSelect).toHaveBeenCalledWith("_submit", undefined, {
      "Which framework?": "React",
      "Which color?": "Blue",
    });
    expect(useQuestionDraftStore.getState().drafts.size).toBe(0);
  });

  it("clears the draft when the card is cancelled", async () => {
    const user = userEvent.setup();
    const { onCancel } = renderQuestion();

    await user.click(screen.getByText("React"));
    await user.click(screen.getByText("Next"));
    await user.click(screen.getByText("Red"));
    await user.click(screen.getByText("Next"));

    await user.click(screen.getByText("Cancel"));

    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(useQuestionDraftStore.getState().drafts.size).toBe(0);
  });
});
