import { cn } from "@posthog/quill";

/**
 * The sessions header's icon buttons: quill's ghost button at the 20px scale.
 * Only the sticky state is ours, because quill styles the transient open state
 * (hover, popup) but has no notion of "search is showing" or "a filter is
 * applied".
 */
export const cnHeaderButton = (active: boolean): string =>
  cn("text-muted-foreground", active && "bg-fill-selected text-foreground");
