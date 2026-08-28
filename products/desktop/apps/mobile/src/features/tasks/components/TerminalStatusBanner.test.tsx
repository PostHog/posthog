import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";
import {
  TerminalStatusBanner,
  type TerminalStatusBannerProps,
} from "./TerminalStatusBanner";

function render(props: TerminalStatusBannerProps) {
  let renderer!: ReturnType<typeof create>;
  act(() => {
    renderer = create(createElement(TerminalStatusBanner, props));
  });
  return renderer;
}

function renderedText(renderer: ReturnType<typeof create>): string {
  const acc: string[] = [];
  const walk = (node: unknown) => {
    if (typeof node === "string") {
      acc.push(node);
    } else if (Array.isArray(node)) {
      node.forEach(walk);
    } else if (node && typeof node === "object" && "children" in node) {
      walk((node as { children: unknown }).children);
    }
  };
  walk(renderer.toJSON());
  return acc.join(" ");
}

describe("TerminalStatusBanner", () => {
  it.each([
    { terminalStatus: "completed", label: "Run completed", button: "Continue" },
    { terminalStatus: "failed", label: "Run failed", button: "Retry" },
    { terminalStatus: "stopped", label: "Run stopped", button: "Continue" },
  ] as const)(
    "shows $label with a $button action for a $terminalStatus run",
    ({ terminalStatus, label, button }) => {
      const text = renderedText(render({ terminalStatus, onRetry: vi.fn() }));
      expect(text).toContain(label);
      expect(text).toContain(button);
    },
  );

  it("does not label a stopped run as failed", () => {
    const text = renderedText(render({ terminalStatus: "stopped" }));
    expect(text).not.toContain("Run failed");
    expect(text).not.toContain("Retry");
  });

  it("fires onRetry when the action is pressed", () => {
    const onRetry = vi.fn();
    const renderer = render({ terminalStatus: "stopped", onRetry });
    const pressable = renderer.root.findAll(
      (node) => node.props.onPress === onRetry,
    )[0];
    act(() => {
      pressable.props.onPress();
    });
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
