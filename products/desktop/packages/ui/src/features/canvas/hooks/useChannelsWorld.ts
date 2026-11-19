import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";

/**
 * Whether any channels chrome is on screen: the spaces layout, or the older
 * channels alpha behind the sidebar toggle. The shell's in-pane header, the
 * right panel and the canvas frame host belong to both, so the routes under
 * `_shell` ask this rather than the layout flag alone.
 */
export function useChannelsWorld(): boolean {
  const layout = useChannelsLayout();
  const toggledOn = useSidebarStore((s) => s.channelsEnabled);
  return layout || toggledOn;
}
