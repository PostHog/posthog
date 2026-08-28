import type { PrVisualConfig } from "@posthog/core/git-interaction/prStatus";

/**
 * A pull request's lifecycle color, as classes for the surfaces that wear it.
 * quill's variants are one neutral palette by design, and these surfaces exist
 * to say merged from closed from open at a glance, so the tint comes from the
 * Radix token layer that the app's color scales already live in.
 *
 * Tailwind only sees class names it can read in the source, so each map spells
 * its classes out. Keeping the maps together means a new lifecycle color is one
 * file to edit rather than five.
 */
type PrToneColor = PrVisualConfig["color"];

/** Icon or label tint on an untinted surface. */
export const PR_TONE_TEXT: Record<PrToneColor, string> = {
  gray: "text-(--gray-11)",
  green: "text-(--green-11)",
  red: "text-(--red-11)",
  purple: "text-(--purple-11)",
};

/** Filled badge, for a control that can be disabled. */
export const PR_TONE_FILL: Record<PrToneColor, string> = {
  gray: "bg-(--gray-3) text-(--gray-11) not-disabled:hover:bg-(--gray-4) not-disabled:hover:text-(--gray-12)",
  green:
    "bg-(--green-3) text-(--green-11) not-disabled:hover:bg-(--green-4) not-disabled:hover:text-(--green-12)",
  red: "bg-(--red-3) text-(--red-11) not-disabled:hover:bg-(--red-4) not-disabled:hover:text-(--red-12)",
  purple:
    "bg-(--purple-3) text-(--purple-11) not-disabled:hover:bg-(--purple-4) not-disabled:hover:text-(--purple-12)",
};

/** Filled pill for the compact command-center badge, which is a plain anchor. */
export const PR_TONE_FILL_COMPACT: Record<PrToneColor, string> = {
  gray: "bg-(--gray-3) text-(--gray-11) hover:bg-(--gray-4)",
  green: "bg-(--green-3) text-(--green-11) hover:bg-(--green-4)",
  red: "bg-(--red-3) text-(--red-11) hover:bg-(--red-4)",
  purple: "bg-(--purple-3) text-(--purple-11) hover:bg-(--purple-4)",
};

/** Divider inside a filled badge, tinted to the badge's own color. */
export const PR_TONE_BORDER: Record<PrToneColor, string> = {
  gray: "border-(--gray-a6)",
  green: "border-(--green-a6)",
  red: "border-(--red-a6)",
  purple: "border-(--purple-a6)",
};

/**
 * How a badge wears its lifecycle state, as props for a quill button. A solid
 * state takes quill's own primary; the rest take their tint.
 *
 * Exported because the dropdown trigger that sits beside the badge in a
 * `ButtonGroup` has to wear the same thing, or the group reads as two controls.
 */
export function prBadgeToneProps(config: PrVisualConfig): {
  variant?: "primary";
  className?: string;
} {
  if (config.solid) return { variant: "primary" };
  return { className: PR_TONE_FILL[config.color] };
}
