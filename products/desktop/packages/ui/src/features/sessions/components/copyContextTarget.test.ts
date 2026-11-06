import { GITHUB_REF_URL_ATTR } from "@posthog/ui/features/editor/components/GithubRefChip";
import { describe, expect, it, vi } from "vitest";
import {
  copyFromContextMenu,
  getGithubRefUrlFromEventTarget,
  getSelectionWithin,
} from "./copyContextTarget";

function buildDom(): {
  icon: HTMLElement;
  label: HTMLElement;
  chip: HTMLElement;
  outside: HTMLElement;
} {
  document.body.innerHTML = `
    <div id="conversation">
      <span ${GITHUB_REF_URL_ATTR}="https://github.com/PostHog/posthog/pull/23985">
        <button id="chip"><svg id="icon"></svg><span id="label">PostHog/posthog#23985</span></button>
      </span>
      <p id="outside">just some prose</p>
    </div>`;
  return {
    icon: document.getElementById("icon") as HTMLElement,
    label: document.getElementById("label") as HTMLElement,
    chip: document.getElementById("chip") as HTMLElement,
    outside: document.getElementById("outside") as HTMLElement,
  };
}

const CHIP_URL = "https://github.com/PostHog/posthog/pull/23985";

describe("getGithubRefUrlFromEventTarget", () => {
  it.each<{
    name: string;
    pick: (dom: ReturnType<typeof buildDom>) => EventTarget | null;
    expected: string | null;
  }>([
    { name: "a nested icon", pick: (dom) => dom.icon, expected: CHIP_URL },
    { name: "the label", pick: (dom) => dom.label, expected: CHIP_URL },
    { name: "the chip button", pick: (dom) => dom.chip, expected: CHIP_URL },
    { name: "non-chip prose", pick: (dom) => dom.outside, expected: null },
    { name: "a non-element target", pick: () => null, expected: null },
  ])("resolves $expected when the target is $name", ({ pick, expected }) => {
    expect(getGithubRefUrlFromEventTarget(pick(buildDom()))).toBe(expected);
  });
});

describe("getSelectionWithin", () => {
  interface Thread {
    first: HTMLElement;
    second: HTMLElement;
    firstText: Text;
    secondText: Text;
  }

  // Built node by node rather than from markup: the indentation between tags
  // becomes text nodes, which a cross-message range would pick up.
  function buildThread(): Thread {
    document.body.innerHTML = "";
    const thread = document.createElement("div");
    const first = document.createElement("div");
    const firstText = document.createTextNode("alpha bravo charlie");
    const second = document.createElement("div");
    const secondText = document.createTextNode("delta echo");
    first.appendChild(firstText);
    second.appendChild(secondText);
    thread.append(first, second);
    document.body.appendChild(thread);
    window.getSelection()?.removeAllRanges();
    return { first, second, firstText, secondText };
  }

  function select(
    start: Node,
    startOffset: number,
    end: Node,
    endOffset: number,
  ) {
    const range = document.createRange();
    range.setStart(start, startOffset);
    range.setEnd(end, endOffset);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
  }

  it.each<{
    name: string;
    highlight: (thread: Thread) => void;
    expected: string | null;
  }>([
    {
      name: "part of the message is highlighted",
      highlight: ({ firstText }) => select(firstText, 6, firstText, 11),
      expected: "bravo",
    },
    {
      name: "the highlight runs on into the next message",
      highlight: ({ firstText, secondText }) =>
        select(firstText, 12, secondText, 5),
      expected: "charliedelta",
    },
    { name: "nothing is highlighted", highlight: () => {}, expected: null },
    {
      name: "only another message is highlighted",
      highlight: ({ secondText }) => select(secondText, 0, secondText, 5),
      expected: null,
    },
    {
      name: "the highlight is only whitespace",
      highlight: ({ firstText }) => select(firstText, 5, firstText, 6),
      expected: null,
    },
  ])("returns $expected when $name", ({ highlight, expected }) => {
    const thread = buildThread();
    highlight(thread);
    expect(getSelectionWithin(thread.first)).toBe(expected);
  });

  it("returns null without a container to check against", () => {
    const { firstText } = buildThread();
    select(firstText, 0, firstText, 5);
    expect(getSelectionWithin(null)).toBeNull();
  });
});

describe("copyFromContextMenu", () => {
  it("defers the clipboard write until after the current task (focus race)", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    copyFromContextMenu("https://github.com/PostHog/posthog/pull/1");

    // Not written synchronously while the menu is still dismissing.
    expect(writeText).not.toHaveBeenCalled();
    await vi.waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(
        "https://github.com/PostHog/posthog/pull/1",
      ),
    );
  });

  it("invokes onSuccess after the deferred write resolves", async () => {
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
    const onSuccess = vi.fn();
    const onError = vi.fn();

    copyFromContextMenu("text", { onSuccess, onError });

    await vi.waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    expect(onError).not.toHaveBeenCalled();
  });

  it("invokes onError when the deferred write rejects", async () => {
    Object.assign(navigator, {
      clipboard: {
        writeText: vi
          .fn()
          .mockRejectedValue(new Error("Document is not focused")),
      },
    });
    const onSuccess = vi.fn();
    const onError = vi.fn();

    copyFromContextMenu("text", { onSuccess, onError });

    await vi.waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    expect(onSuccess).not.toHaveBeenCalled();
  });
});
