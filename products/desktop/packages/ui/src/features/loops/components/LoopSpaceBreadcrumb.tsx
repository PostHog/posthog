import { ChannelBreadcrumb } from "@posthog/ui/features/canvas/components/ChannelBreadcrumb";
import {
  channelPageIcon,
  channelPageLabel,
} from "@posthog/ui/features/canvas/components/channelPages";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useNavigate } from "@tanstack/react-router";

/**
 * Header breadcrumb for a loop that belongs to a space:
 * "{space} / Loops / {loop}", with the space and Loops segments both linking
 * back. Loops live outside the space routes (/loops/…), so without this a
 * space-attached loop is a dead end.
 *
 * Render this only when the spaces layout is on and the loop has a context
 * target — callers pass `null` to `useSetHeaderContent` otherwise, which
 * leaves a project-level loop with no breadcrumb row at all.
 */
export function LoopSpaceBreadcrumb({
  folderId,
  spaceName,
  leafLabel,
}: {
  /** Desktop folder id of the attached space (`context_target.folder_id`). */
  folderId: string;
  /** Name stamped on the loop, used until the live space list resolves. */
  spaceName: string;
  leafLabel: string;
}) {
  const navigate = useNavigate();
  // The loop's stored name can go stale after a rename, so prefer the live one.
  const { channels } = useChannels();
  const liveName = channels.find((c) => c.id === folderId)?.name;

  return (
    <ChannelBreadcrumb
      channelName={liveName ?? spaceName}
      channelId={folderId}
      middle={{
        icon: channelPageIcon("loops", { size: 12 }),
        label: channelPageLabel("loops"),
        onClick: () =>
          void navigate({
            to: "/spaces/$channelId/loops",
            params: { channelId: folderId },
          }),
      }}
      leafLabel={leafLabel}
    />
  );
}
