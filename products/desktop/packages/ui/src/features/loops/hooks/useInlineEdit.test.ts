import { act, renderHook } from "@testing-library/react";
import type { ChangeEvent, FocusEvent, KeyboardEvent } from "react";
import { describe, expect, it, vi } from "vitest";
import { type InlineEditOptions, useInlineEdit } from "./useInlineEdit";

function setup(overrides: Partial<InlineEditOptions> = {}) {
  const onCommit = vi.fn();
  const view = renderHook((props: InlineEditOptions) => useInlineEdit(props), {
    initialProps: {
      current: "hello",
      isPending: false,
      onCommit,
      ...overrides,
    },
  });
  return { onCommit, view };
}

function change(value: string) {
  return { currentTarget: { value } } as ChangeEvent<HTMLInputElement>;
}

function blur(value: string) {
  return { currentTarget: { value } } as FocusEvent<HTMLInputElement>;
}

function keyDown(key: string, opts: { shiftKey?: boolean } = {}) {
  const blurFn = vi.fn();
  const preventDefault = vi.fn();
  return {
    event: {
      key,
      shiftKey: opts.shiftKey ?? false,
      preventDefault,
      currentTarget: { blur: blurFn },
    } as unknown as KeyboardEvent<HTMLElement>,
    blurFn,
    preventDefault,
  };
}

describe("useInlineEdit", () => {
  it("enters and exits edit mode", () => {
    const { view } = setup();
    expect(view.result.current.isEditing).toBe(false);
    act(() => view.result.current.startEditing());
    expect(view.result.current.isEditing).toBe(true);
    expect(view.result.current.draft).toBe("hello");
    act(() => view.result.current.reset());
    expect(view.result.current.isEditing).toBe(false);
  });

  it("commits a changed value on blur", () => {
    const { onCommit, view } = setup();
    act(() => view.result.current.startEditing());
    act(() => view.result.current.inputProps.onChange(change("world")));
    act(() => view.result.current.inputProps.onBlur(blur("world")));
    expect(onCommit).toHaveBeenCalledWith("world", expect.anything());
  });

  it("does not commit an unchanged value", () => {
    const { onCommit, view } = setup();
    act(() => view.result.current.startEditing());
    act(() => view.result.current.inputProps.onBlur(blur("  hello  ")));
    expect(onCommit).not.toHaveBeenCalled();
    expect(view.result.current.isEditing).toBe(false);
  });

  it("rejects an empty value when allowEmpty is false", () => {
    const { onCommit, view } = setup();
    act(() => view.result.current.startEditing());
    act(() => view.result.current.inputProps.onBlur(blur("   ")));
    expect(onCommit).not.toHaveBeenCalled();
    expect(view.result.current.isEditing).toBe(false);
  });

  it("commits an empty value when allowEmpty is true", () => {
    const { onCommit, view } = setup({ current: "note", allowEmpty: true });
    act(() => view.result.current.startEditing());
    act(() => view.result.current.inputProps.onBlur(blur("   ")));
    expect(onCommit).toHaveBeenCalledWith("", expect.anything());
  });

  it("does not commit while a save is pending", () => {
    const { onCommit, view } = setup({ isPending: true });
    act(() => view.result.current.startEditing());
    act(() => view.result.current.inputProps.onBlur(blur("world")));
    expect(onCommit).not.toHaveBeenCalled();
  });

  it("Escape reverts and skips the resulting blur save", () => {
    const { onCommit, view } = setup();
    act(() => view.result.current.startEditing());
    act(() => view.result.current.inputProps.onChange(change("world")));

    const escapeKey = keyDown("Escape");
    act(() => view.result.current.inputProps.onKeyDown(escapeKey.event));
    expect(escapeKey.blurFn).toHaveBeenCalled();
    expect(view.result.current.isEditing).toBe(false);

    act(() => view.result.current.inputProps.onBlur(blur("world")));
    expect(onCommit).not.toHaveBeenCalled();
  });

  it("commits on Enter only when configured", () => {
    const never = keyDown("Enter");
    const { view: neverView } = setup({ commitOnEnter: "never" });
    act(() => neverView.result.current.inputProps.onKeyDown(never.event));
    expect(never.blurFn).not.toHaveBeenCalled();

    const enter = keyDown("Enter");
    const { view: enterView } = setup({ commitOnEnter: "enter" });
    act(() => enterView.result.current.inputProps.onKeyDown(enter.event));
    expect(enter.preventDefault).toHaveBeenCalled();
    expect(enter.blurFn).toHaveBeenCalled();
  });

  it("Shift+Enter inserts a newline when commitOnEnter is enter-no-shift", () => {
    const shift = keyDown("Enter", { shiftKey: true });
    const { view } = setup({ commitOnEnter: "enter-no-shift" });
    act(() => view.result.current.inputProps.onKeyDown(shift.event));
    expect(shift.blurFn).not.toHaveBeenCalled();

    const plain = keyDown("Enter");
    const { view: plainView } = setup({ commitOnEnter: "enter-no-shift" });
    act(() => plainView.result.current.inputProps.onKeyDown(plain.event));
    expect(plain.blurFn).toHaveBeenCalled();
  });
});
