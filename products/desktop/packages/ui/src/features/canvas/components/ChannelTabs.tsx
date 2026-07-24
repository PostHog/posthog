import { Button, cn } from "@posthog/quill";
import { LOOPS_FLAG } from "@posthog/shared";
import { CHANNEL_SECTIONS } from "@posthog/ui/features/canvas/channelSections";
import { ChannelPinnedMenu } from "@posthog/ui/features/canvas/components/ChannelPinnedMenu";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { Link, useRouterState } from "@tanstack/react-router";

const TABS = CHANNEL_SECTIONS.map((s) => ({
  key: s.key,
  label: s.label,
  to: `/website/$channelId/${s.key}` as const,
}));

// Home / History / Artifacts tab switcher shown in the channel header bar, with
// a Pinned quick-access menu alongside. Pathname-driven active state (the
// codebase's convention) rather than Link's activeProps.
export function ChannelTabs({ channelId }: { channelId: string }) {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const loopsEnabled = useFeatureFlag(LOOPS_FLAG, import.meta.env.DEV);
  const tabs = loopsEnabled ? TABS : TABS.filter((tab) => tab.key !== "loops");

  return (
    <nav className="flex items-center gap-px">
      {tabs.map((tab) => {
        const href = tab.to.replace("$channelId", channelId);
        const active = pathname === href;
        return (
          <Button
            key={tab.label}
            variant="default"
            size="sm"
            data-selected={active || undefined}
            className={cn(active && "bg-fill-selected")}
            render={<Link to={tab.to} params={{ channelId }} />}
          >
            {tab.label}
          </Button>
        );
      })}
      <ChannelPinnedMenu channelId={channelId} />
    </nav>
  );
}
