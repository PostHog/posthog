import type { Node } from "@tiptap/core";
import type { ReactNode } from "react";

/**
 * The hover card an inline reference opens: one title, one meta line, one
 * action, or a card of its own when the kind already has a richer one.
 */
export interface InlineRefCard {
  title: string;
  meta?: ReactNode;
  action?: { label: string; onSelect: () => void };
  /** Replaces the default body. Mounted only while the card is open; `close` shuts the card. */
  render?: (close: () => void) => ReactNode;
}

/** What a kind reads about itself, once, per rendered reference. */
export interface InlineRefState {
  label: string;
  mark?: ReactNode;
  card?: InlineRefCard;
  onOpen?: () => void;
}

/**
 * One kind of inline reference.
 *
 * A kind describes itself and reads itself. It never touches ProseMirror, the
 * popover, or the stylesheet, so adding a kind is this object plus a hook.
 */
export interface InlineRefKind<A> {
  name: string;
  attributes: Record<string, { default: unknown }>;
  parseTag: string;
  /** Written to the DOM by both the node view and `renderHTML`. */
  domAttributes: (attrs: A) => Record<string, string>;
  /** The text `renderHTML` writes when no node view runs. */
  fallbackLabel: (attrs: A) => string;
  /** Extend an existing node instead of creating one. */
  base?: Node;
  useRef: (attrs: A) => InlineRefState;
}
