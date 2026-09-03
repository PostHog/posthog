import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";
import { ConsentPanel } from "./ConsentPanel";

type Renderer = NonNullable<ReturnType<typeof create>>;

function render(props: Partial<Parameters<typeof ConsentPanel>[0]> = {}) {
  let renderer!: Renderer;
  act(() => {
    renderer = create(
      createElement(ConsentPanel, {
        organizationName: "Acme",
        needsAiConsent: true,
        needsBetaTerms: false,
        isAdmin: true,
        onAcceptAi: vi.fn(async () => {}),
        onAcceptBeta: vi.fn(async () => {}),
        ...props,
      }),
    );
  });
  return renderer;
}

function texts(renderer: Renderer): string[] {
  return renderer.root
    .findAll((node) => typeof node.props.children === "string")
    .map((node) => node.props.children as string);
}

function acceptButton(renderer: Renderer) {
  return renderer.root.find(
    (node) =>
      typeof node.props.onPress === "function" && "disabled" in node.props,
  );
}

describe("ConsentPanel", () => {
  it("shows the accept action for an admin", () => {
    const renderer = render({ isAdmin: true });
    expect(texts(renderer)).toContain("Approve AI data processing");
  });

  it("directs a non-admin to an org admin with no accept action", () => {
    const renderer = render({ isAdmin: false });
    const content = texts(renderer);
    expect(content).toContain(
      "Ask an organization admin to approve AI data processing.",
    );
    expect(content).not.toContain("Approve AI data processing");
  });

  it("cannot be double-submitted while a request is in flight", async () => {
    let resolveAccept!: () => void;
    const onAcceptAi = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveAccept = resolve;
        }),
    );
    const renderer = render({ isAdmin: true, onAcceptAi });

    act(() => {
      acceptButton(renderer).props.onPress();
    });
    act(() => {
      acceptButton(renderer).props.onPress();
    });

    expect(onAcceptAi).toHaveBeenCalledTimes(1);
    expect(acceptButton(renderer).props.disabled).toBe(true);

    await act(async () => {
      resolveAccept();
    });

    expect(acceptButton(renderer).props.disabled).toBe(false);
  });
});
