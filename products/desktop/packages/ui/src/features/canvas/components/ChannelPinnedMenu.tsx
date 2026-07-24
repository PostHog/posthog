import { CaretDownIcon, PushPinIcon } from "@phosphor-icons/react";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { iconForTemplate } from "@posthog/ui/features/canvas/components/canvasTemplateIcon";
import { useDashboards } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { track } from "@posthog/ui/shell/analytics";
import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";

// A quick-access dropdown next to the channel tabs listing the channel's pinned
// canvases (pinned from a canvas's "…" menu), most recently pinned first. Opens
// the selected canvas.
export function ChannelPinnedMenu({ channelId }: { channelId: string }) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const { dashboards } = useDashboards(channelId);

  const pinned = dashboards
    .filter((d) => d.pinnedAt != null)
    .sort((a, b) => (b.pinnedAt ?? 0) - (a.pinnedAt ?? 0));

  const openCanvas = (dashboardId: string) => {
    track(ANALYTICS_EVENTS.DASHBOARD_ACTION, {
      action_type: "open",
      surface: "pinned",
      channel_id: channelId,
      dashboard_id: dashboardId,
    });
    void navigate({
      to: "/website/$channelId/dashboards/$dashboardId",
      params: { channelId, dashboardId },
    });
  };

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger
        render={
          <Button size="sm">
            <PushPinIcon size={14} />
            Pinned
            <CaretDownIcon size={12} />
          </Button>
        }
      />
      <DropdownMenuContent
        align="start"
        side="bottom"
        sideOffset={4}
        className="w-fit"
      >
        {pinned.length === 0 ? (
          <DropdownMenuItem disabled>No pinned canvases</DropdownMenuItem>
        ) : (
          pinned.map((d) => (
            <DropdownMenuItem key={d.id} onClick={() => openCanvas(d.id)}>
              {iconForTemplate(d.templateId, {
                size: 14,
                className: "text-violet-9",
              })}
              <span className="truncate">{d.name}</span>
            </DropdownMenuItem>
          ))
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
