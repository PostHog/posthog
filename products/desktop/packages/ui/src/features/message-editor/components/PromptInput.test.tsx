import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const editorState = vi.hoisted(() => ({ isEmpty: false }));
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
    getText: vi.fn(),
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
  InputGroup: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  InputGroupAddon: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  InputGroupButton: ({
    children,
    ...props
  }: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button type="button" {...props}>
      {children}
    </button>
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
    expect(send).toBeEnabled();
  });

  it("disables Send when the editor is empty", () => {
    editorState.isEmpty = true;

    renderInput({});

    const send = screen.getByRole("button", { name: "Send message" });
    expect(send).toBeDisabled();
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
