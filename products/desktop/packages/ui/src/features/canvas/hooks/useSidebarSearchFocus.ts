import { useSidebarSearchStore } from "@posthog/ui/features/canvas/stores/sidebarSearchStore";
import { type RefObject, useEffect } from "react";

export function useSidebarSearchFocus(
  ref: RefObject<HTMLInputElement | null>,
): void {
  const focusRequest = useSidebarSearchStore((state) => state.focusRequest);

  useEffect(() => {
    if (focusRequest === 0) return;
    const input = ref.current;
    if (!input || input.closest("[inert]")) return;
    // Claim after the inert guard so an offscreen header leaves the request for
    // the visible one, and so each request focuses a single header once.
    if (!useSidebarSearchStore.getState().claimFocus(focusRequest)) return;
    input.focus();
    input.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Home", bubbles: true }),
    );
    input.select();
  }, [focusRequest, ref]);
}
