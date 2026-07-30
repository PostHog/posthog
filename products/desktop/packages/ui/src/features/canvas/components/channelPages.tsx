import {
  BookOpenTextIcon,
  ChatsCircleIcon,
  ClockCounterClockwiseIcon,
  type IconProps,
  PackageIcon,
  ShapesIcon,
} from "@phosphor-icons/react";
import { LoopIcon } from "@posthog/ui/primitives/LoopIcon";
import type { ComponentType, ReactNode } from "react";

/**
 * The pages inside a space, and how each one is named and drawn. One table so
 * the sidebar rows, the header breadcrumb leaf, and anything else that points
 * at a space page can't drift apart — add a page here, not at the call sites.
 *
 * `home` is the space's feed. It's both the root route and a named page, so it
 * reads as "{space} / Feed" like every sibling rather than a bare space name.
 *
 * Route segments and browser-tab names live in `channelSections.ts`, which is
 * plain data (no React) because non-UI code reads it.
 */
export type ChannelPageKey =
  | "home"
  | "context"
  | "loops"
  | "artifacts"
  | "canvases"
  | "history";

export const CHANNEL_PAGES: Record<
  ChannelPageKey,
  { label: string; Icon: ComponentType<IconProps> }
> = {
  home: { label: "Feed", Icon: ChatsCircleIcon },
  context: { label: "Context", Icon: BookOpenTextIcon },
  loops: { label: "Loops", Icon: LoopIcon },
  artifacts: { label: "Artifacts", Icon: PackageIcon },
  canvases: { label: "Canvases", Icon: ShapesIcon },
  history: { label: "Recents", Icon: ClockCounterClockwiseIcon },
};

export function channelPageLabel(key: ChannelPageKey): string {
  return CHANNEL_PAGES[key].label;
}

export function channelPageIcon(
  key: ChannelPageKey,
  opts?: { size?: number; className?: string },
): ReactNode {
  const { Icon: PageIcon } = CHANNEL_PAGES[key];
  return <PageIcon size={opts?.size ?? 16} className={opts?.className} />;
}
