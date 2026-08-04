import { Switch } from "@posthog/quill";
import { AllSpacesSection } from "@posthog/ui/features/canvas/components/AllSpacesSection";
import { ChannelNav } from "@posthog/ui/features/canvas/components/ChannelNav";
import { SpaceSection } from "@posthog/ui/features/canvas/components/SpaceSection";
import { useStarredChannelSlots } from "@posthog/ui/features/canvas/hooks/useStarredChannelSlots";
import { useSpacesSidebarStore } from "@posthog/ui/features/canvas/stores/spacesSidebarStore";

/**
 * The static spaces nav: the shell keeps ChannelNav (the highlighted icon
 * row — Inbox, Activity, Command Center and Settings already live there),
 * then the sidebar-wide "My tasks" filter, then every pinned space with its
 * tasks foldable inline. The All spaces directory is docked at the bottom and
 * opens upward; the pinned list is what scrolls in between.
 */
export function SpacesSidebarNav() {
  const { slots: pinnedSpaces } = useStarredChannelSlots();
  const onlyMyTasks = useSpacesSidebarStore((s) => s.onlyMyTasks);
  const toggleOnlyMyTasks = useSpacesSidebarStore((s) => s.toggleOnlyMyTasks);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <ChannelNav />

      {/* One filter over every space's task list below. */}
      <div className="flex shrink-0 items-center justify-between px-3 pb-1.5 text-[12px] text-muted-foreground">
        My tasks
        <Switch
          size="sm"
          aria-label="Show only my tasks"
          checked={onlyMyTasks}
          onCheckedChange={toggleOnlyMyTasks}
        />
      </div>

      {/* Pinned (starred) spaces; #me first. */}
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        <div className="flex flex-col gap-px">
          {pinnedSpaces.map((space) => (
            <SpaceSection key={space.id} channel={space} />
          ))}
        </div>
      </div>

      {/* Every space in the project, docked at the bottom. */}
      <AllSpacesSection />
    </div>
  );
}
