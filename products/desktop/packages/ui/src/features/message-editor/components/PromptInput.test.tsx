import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const editorState = vi.hoisted(() => ({ isEmpty: false, text: "ship it" }));
const track = vi.hoisted(() => vi.fn());
const settingsState = vi.hoisted(() => ({ slotMachineMode: false }));

vi.mock("../tiptap/useTiptapEditor", () => ({
  useTiptapEditor: () => ({
    editor: null,
    isReady: true,
    isEmpty: editorState.isEmpty,
    isBashMode: false,
    submit: vi.fn(),
    focus: vi.fn(),
    blur: vi.fn(),
    clear: vi.fn(),
    getText: () => (editorState.isEmpty ? "" : editorState.text),
    getContent: vi.fn(),
    setContent: vi.fn(),
    insertChip: vi.fn(),
    removeChipById: vi.fn(),
    replaceChipAttrs: vi.fn(),
    attachments: [],
    addAttachment: vi.fn(),
    removeAttachment: vi.fn(),
  }),
}));

vi.mock("@posthog/ui/shell/analytics", () => ({ track }));

vi.mock("@posthog/ui/features/settings/settingsStore", () => ({
  useSettingsStore: (selector: (s: typeof settingsState) => unknown) =>
    selector(settingsState),
}));

vi.mock("../../skills/useSkills", () => ({
  useSkills: () => ({ data: [] }),
}));

vi.mock("../draftStore", () => ({
  useDraftStore: Object.assign(
    (selector: (s: unknown) => unknown) =>
      selector({ focusRequested: {}, actions: { clearFocusRequest: vi.fn() } }),
    {
      getState: () => ({
        actions: { setCommands: vi.fn(), clearCommands: vi.fn() },
      }),
    },
  ),
}));

vi.mock("./AttachmentMenu", () => ({ AttachmentMenu: () => null }));
vi.mock("./AttachmentsBar", () => ({ AttachmentsBar: () => null }));
vi.mock("./SlotMachineSubmit", () => ({
  SlotMachineSubmit: ({
    disabled,
    onSubmit,
  }: {
    disabled?: boolean;
    onSubmit?: () => void;
  }) => (
    <button
      type="button"
      aria-label="Slot machine submit"
      disabled={disabled}
      onClick={onSubmit}
    />
  ),
}));

vi.mock("@posthog/quill", () => ({
  // Mirrors quill's Button: `loading` swaps the label for a spinner and blocks
  // activation.
  Button: ({
    children,
    loading,
    disabled,
    onClick,
    ...props
  }: React.ButtonHTMLAttributes<HTMLButtonElement> & {
    loading?: boolean;
  }) => (
    // Mirrors quill, which leaves the native attribute off and marks the
    // button aria-disabled, so a refused press still dispatches a click.
    <button
      type="button"
      aria-disabled={disabled || loading || undefined}
      aria-busy={loading || undefined}
      onClick={disabled || loading ? undefined : onClick}
      {...props}
    >
      {children}
    </button>
  ),
  InputGroup: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  InputGroupAddon: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
}));

import { PromptInput } from "./PromptInput";

function renderInput(props: Partial<React.ComponentProps<typeof PromptInput>>) {
  return render(
    <Theme>
      <PromptInput sessionId="s1" {...props} />
    </Theme>,
  );
}

describe("PromptInput submit/stop affordance", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    editorState.isEmpty = false;
    editorState.text = "ship it";
    settingsState.slotMachineMode = false;
  });

  it("shows Stop (not Send) while loading and calls onCancel when clicked", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();

    renderInput({ isLoading: true, onCancel });

    const stop = screen.getByRole("button", { name: "Stop" });
    expect(
      screen.queryByRole("button", { name: "Send message" }),
    ).not.toBeInTheDocument();

    await user.click(stop);
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("keeps Send enabled mid-turn when no cancel handler (queue/steer path)", () => {
    // isLoading true but no onCancel => inStopMode is false, so the composer
    // must still expose an enabled Send so messages queue/steer mid-turn.
    // Regression guard: adding `|| isLoading` to submitBlocked disables this.
    renderInput({ isLoading: true });

    const send = screen.getByRole("button", { name: "Send message" });
    expect(send).not.toHaveAttribute("aria-disabled");
  });

  it("disables Send when the editor is empty", () => {
    editorState.isEmpty = true;

    renderInput({});

    const send = screen.getByRole("button", { name: "Send message" });
    expect(send).toHaveAttribute("aria-disabled", "true");
  });

  it("marks Send busy on click, before the surface reports anything", async () => {
    const user = userEvent.setup();
    // Surfaces flip their own busy flags only after a round trip, so a send
    // that never resolves must still register as pressed.
    const onSubmitClick = vi.fn();

    renderInput({ onSubmitClick });

    const send = screen.getByRole("button", { name: "Send message" });
    await user.click(send);

    expect(onSubmitClick).toHaveBeenCalledOnce();
    expect(send).toHaveAttribute("aria-busy", "true");
    expect(send).toHaveAttribute("aria-disabled", "true");
  });

  it("names the blocker instead of asking for a message already typed", async () => {
    const user = userEvent.setup();

    renderInput({
      submitDisabledExternal: true,
      submitDisabledReason: "Pick a repository first",
    });

    await user.hover(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByRole("tooltip")).toHaveTextContent(
      "Pick a repository first",
    );
  });

  it("falls back to the empty-composer hint only when the composer is empty", async () => {
    const user = userEvent.setup();
    editorState.isEmpty = true;

    renderInput({});

    await user.hover(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByRole("tooltip")).toHaveTextContent(
      "Enter a message",
    );
  });

  it("records a refused press on a composer that already holds a prompt", async () => {
    const user = userEvent.setup();

    renderInput({
      surface: "new_task",
      submitDisabledExternal: true,
      submitDisabledReason: "Pick a repository first",
    });

    await user.click(screen.getByRole("button", { name: "Send message" }));

    expect(track).toHaveBeenCalledWith("Prompt submit blocked", {
      surface: "new_task",
      trigger: "click",
      reason: "Pick a repository first",
      prompt_length_chars: "ship it".length,
    });
  });

  it("does not record a refused press when the composer is empty", async () => {
    const user = userEvent.setup();
    editorState.isEmpty = true;

    renderInput({});

    await user.click(screen.getByRole("button", { name: "Send message" }));

    expect(track).not.toHaveBeenCalled();
  });

  it("keeps Send busy while the surface is both loading and untypeable", () => {
    // The new-task composer's whole task creation looks like this.
    renderInput({ disabled: true, isLoading: true });

    const send = screen.getByRole("button", { name: "Send message" });
    expect(send).toHaveAttribute("aria-busy", "true");
  });
});

describe("PromptInput escape handling", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    editorState.isEmpty = false;
    settingsState.slotMachineMode = false;
  });

  it("cancels the queued-message edit on Escape", async () => {
    const user = userEvent.setup();
    const onCancelEdit = vi.fn();

    renderInput({ isEditingQueued: true, onCancelEdit });

    await user.keyboard("{Escape}");
    expect(onCancelEdit).toHaveBeenCalledOnce();
  });

  it("prioritizes cancelling the edit over stopping the run on Escape", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    const onCancelEdit = vi.fn();

    renderInput({
      isLoading: true,
      onCancel,
      isEditingQueued: true,
      onCancelEdit,
    });

    await user.keyboard("{Escape}");
    expect(onCancelEdit).toHaveBeenCalledOnce();
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("still stops the run on Escape when not editing", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();

    renderInput({ isLoading: true, onCancel, isEditingQueued: false });

    await user.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledOnce();
  });
});
