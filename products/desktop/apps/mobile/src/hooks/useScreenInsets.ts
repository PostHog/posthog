import { useMemo } from "react";
import { useSafeAreaInsets } from "react-native-safe-area-context";

/**
 * Single source of truth for screen spacing policy.
 *
 * The device safe-area insets (notch, home indicator, Android soft buttons)
 * come from `useSafeAreaInsets()` and vary per device — we never hardcode
 * those. What this hook centralizes is the *gap we add on top of the inset*,
 * which was previously hand-written per screen with a scatter of magic numbers
 * (12 / 16 / 20 / 24 / 32 / 40 / 50). Those are rationalized into one small
 * scale so spacing is consistent across surfaces and tunable in one place.
 */

/**
 * Standard content gaps layered ON TOP of the bottom safe-area inset.
 * Pick by intent, not by pixel value.
 */
export const BOTTOM_GAP = {
  /** Bottom sheets, sticky footers, tight composers. */
  compact: 12,
  /** Scrollable form / list content in modals and detail screens. */
  default: 24,
  /** Filter sheets and sections that want extra breathing room. */
  roomy: 40,
} as const;

/** Standard gap above the top safe-area inset for page-sheet content. */
const TOP_GAP = 8;

/** Bottom-right floating action buttons sit this far above the inset. */
const FAB_GAP = 20;

/**
 * The chat composer keeps at least this much bottom space when the keyboard
 * is closed, even on devices that report a zero bottom inset (e.g. older
 * Android with hardware buttons).
 */
export const COMPOSER_MIN_BOTTOM = 50;

export type BottomGapVariant = keyof typeof BOTTOM_GAP;

export function useScreenInsets() {
  const insets = useSafeAreaInsets();

  return useMemo(() => {
    return {
      /** Raw device insets, for cases the helpers below don't cover. */
      insets,
      /** Bottom padding = device inset + the standard gap for this surface. */
      bottom: (variant: BottomGapVariant = "default") =>
        insets.bottom + BOTTOM_GAP[variant],
      /**
       * Top padding for bottom-sheet / filter-menu content (inset + the fixed
       * sheet top gap). Scoped to sheets on purpose — full screens that need a
       * measured header height should compute `insets.top + <headerHeight>`
       * directly rather than reaching for this.
       */
      sheetContentTop: () => insets.top + TOP_GAP,
      /**
       * Bottom offset for a floating action button. The `+FAB_GAP` is a
       * frozen domain-specific choice, not a `BOTTOM_GAP` variant — there is
       * no `fabBottom("roomy")`. Tune `FAB_GAP` if every FAB should move.
       */
      fabBottom: () => insets.bottom + FAB_GAP,
      /**
       * Chat composer bottom margin floor. The `COMPOSER_MIN_BOTTOM` floor is
       * a frozen domain-specific choice, not a `BOTTOM_GAP` variant — there is
       * no `composerBottom("compact")`.
       */
      composerBottom: () => Math.max(insets.bottom, COMPOSER_MIN_BOTTOM),
    };
  }, [insets]);
}
