import { useRef } from "react";

export interface FromSuggestionTracker {
  /** A suggestion chip seeded the composer. */
  mark: () => void;
  /** The user typed over the seeded prompt. */
  clear: () => void;
  /** Read the flag for the outgoing prompt and reset it. */
  consume: () => boolean;
}

// Tracks whether the composer's current draft was seeded by a suggestion chip,
// so the eventual send can be attributed to it. Shared by the canvas and
// freeform chat panels, which drive the same attribution. The flag is a ref
// (not state) — it never needs to trigger a re-render.
export function useFromSuggestion(): FromSuggestionTracker {
  const ref = useRef(false);
  // Stable object identity across renders so it's safe in deps/handlers.
  const api = useRef<FromSuggestionTracker>({
    mark: () => {
      ref.current = true;
    },
    clear: () => {
      ref.current = false;
    },
    consume: () => {
      const value = ref.current;
      ref.current = false;
      return value;
    },
  });
  return api.current;
}
