import { GITHUB_REF_URL_ATTR } from "@posthog/ui/features/editor/components/GithubRefChip";
import { describe, expect, it, vi } from "vitest";
import {
  copyFromContextMenu,
  getGithubRefUrlFromEventTarget,
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
