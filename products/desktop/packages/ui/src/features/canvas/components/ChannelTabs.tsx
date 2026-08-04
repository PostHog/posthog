import { Button, cn } from "@posthog/quill";
import { LOOPS_FLAG } from "@posthog/shared";
import { CHANNEL_SECTIONS } from "@posthog/ui/features/canvas/channelSections";
import { ChannelPinnedMenu } from "@posthog/ui/features/canvas/components/ChannelPinnedMenu";
import { channelPageLabel } from "@posthog/ui/features/canvas/components/channelPages";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { Link, useRouterState } from "@tanstack/react-router";

const TABS = CHANNEL_SECTIONS.map((s) => ({
  key: s.key,
  label: s.label,
  to: `/website/$channelId/${s.key}` as const,
}));

// The space-page variant: Feed leads (it's the space itself, and the way back
// once you've tabbed away), Context follows it, and the labels come from the
// channelPages table ("Context", not the legacy "CONTEXT.md").
const SPACE_TABS = (["context", "loops", "artifacts", "history"] as const).map(
  (key) => ({
    key,
    label: channelPageLabel(key),
    to: `/website/$channelId/${key}` as const,
  }),
);

// Home / History / Artifacts tab switcher shown in the channel header bar, with
// a Pinned quick-access menu alongside. Pathname-driven active state (the
// codebase's convention) rather than Link's activeProps.
export function ChannelTabs({
  channelId,
  includeHome,
}: {
  channelId: string;
  /**
   * Adds a leading Feed tab for the space root. On: the header is the only tab
   * strip (channels layout). Off: legacy header, where the channel pill beside
   * this nav already links home.
   */
  includeHome?: boolean;
}) {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const loopsEnabled = useFeatureFlag(LOOPS_FLAG, import.meta.env.DEV);
  const sectionTabs = includeHome ? SPACE_TABS : TABS;
  const tabs = loopsEnabled
    ? sectionTabs
    : sectionTabs.filter((tab) => tab.key !== "loops");
  const home = `/website/${channelId}`;

  return (
    <nav className="flex items-center gap-px">
      {includeHome && (
        <Button
          variant="default"
          size="sm"
          data-selected={pathname === home || undefined}
          className={cn(pathname === home && "bg-fill-selected")}
          render={<Link to="/website/$channelId" params={{ channelId }} />}
        >
          {channelPageLabel("home")}
        </Button>
      )}
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
