import { GithubRefChip } from "@posthog/ui/features/editor/components/GithubRefChip";
import {
  copyFromContextMenu,
  getGithubRefUrlFromEventTarget,
} from "@posthog/ui/features/sessions/components/copyContextTarget";
import { ContextMenu, Theme } from "@radix-ui/themes";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const PR_URL = "https://github.com/PostHog/posthog/pull/63995";

// Radix's menu content mounts a scroll-area that observes resizes; jsdom lacks it.
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

/**
 * Mirrors the exact context-menu wiring in SessionView: a ContextMenu.Trigger
 * whose child captures the right-clicked URL in a ref, and a "Copy" item that
 * copies the captured URL (falling back to the text selection).
 */
function Harness() {
  const copyTargetUrlRef = useRef<string | null>(null);
  const handleContextMenu = (e: React.MouseEvent) => {
    copyTargetUrlRef.current = getGithubRefUrlFromEventTarget(e.target);
  };
  return (
    <Theme>
      <ContextMenu.Root>
        <ContextMenu.Trigger>
          {/** biome-ignore lint/a11y/noStaticElementInteractions: test harness */}
          <div onContextMenu={handleContextMenu}>
            <span>The draft PR is up: </span>
            <GithubRefChip href={PR_URL} kind="pr">
              PostHog/posthog#63995
            </GithubRefChip>
          </div>
        </ContextMenu.Trigger>
        <ContextMenu.Content>
          <ContextMenu.Item
            onSelect={() => {
              const url = copyTargetUrlRef.current;
              const text = url ?? window.getSelection()?.toString();
              if (!text) {
                return;
              }
              copyFromContextMenu(text);
            }}
          >
            Copy
          </ContextMenu.Item>
        </ContextMenu.Content>
      </ContextMenu.Root>
    </Theme>
  );
}

describe("conversation context-menu copy (integration)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("copies the PR URL when right-clicking the chip and choosing Copy", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    render(<Harness />);

    // Right-click the chip label, exactly as a user would.
    const label = screen.getByText("PostHog/posthog#63995");
    fireEvent.contextMenu(label);

    const copyItem = await screen.findByText("Copy");
    await userEvent.click(copyItem);

    // The write is deferred until after the menu closes (focus race), so wait.
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(PR_URL));
  });

  it("falls back to the text selection when the right-click misses a chip", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    vi.spyOn(window, "getSelection").mockReturnValue({
      toString: () => "some selected prose",
    } as Selection);

    render(<Harness />);

    fireEvent.contextMenu(screen.getByText(/The draft PR is up/));
    await userEvent.click(await screen.findByText("Copy"));

    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith("some selected prose"),
    );
  });

  it("copies nothing when there is neither a chip URL nor a selection", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    vi.spyOn(window, "getSelection").mockReturnValue({
      toString: () => "",
    } as Selection);

    render(<Harness />);

    fireEvent.contextMenu(screen.getByText(/The draft PR is up/));
    await userEvent.click(await screen.findByText("Copy"));

    // Flush the deferred-write tick so a wrongful copy would have fired by now.
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(writeText).not.toHaveBeenCalled();
  });
});
