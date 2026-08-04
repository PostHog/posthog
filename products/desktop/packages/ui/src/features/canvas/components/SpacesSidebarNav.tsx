import { AllSpacesSection } from "@posthog/ui/features/canvas/components/AllSpacesSection";
import { ChannelNav } from "@posthog/ui/features/canvas/components/ChannelNav";
import { SpaceSection } from "@posthog/ui/features/canvas/components/SpaceSection";
import { useStarredChannelSlots } from "@posthog/ui/features/canvas/hooks/useStarredChannelSlots";

/**
 * The static spaces nav: the shell keeps ChannelNav (the highlighted icon
 * row — Inbox, Activity, Command Center and Settings already live there), then
 * every pinned space with its tasks expandable inline, then the All spaces
 * directory. No Home/Tasks/Inbox rows: the icon row covers them, and repeating
 * them as full-width rows pushed the spaces — the point of this sidebar —
 * below the fold.
 */
export function SpacesSidebarNav() {
  const { slots: pinnedSpaces } = useStarredChannelSlots();

  return (
    <>
      <ChannelNav />

      {/* Pinned (starred) spaces; #me first. */}
      <div className="flex flex-col gap-px px-2 pb-1">
        {pinnedSpaces.map((space) => (
          <SpaceSection key={space.id} channel={space} />
        ))}
      </div>

      {/* Every space in the project */}
      <AllSpacesSection />
    </>
  );
}
