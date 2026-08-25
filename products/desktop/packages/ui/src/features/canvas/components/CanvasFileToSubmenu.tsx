import { FolderSimpleIcon } from "@phosphor-icons/react";
import { DropdownMenuSub, DropdownMenuSubTrigger } from "@posthog/quill";
import { PROJECT_BLUEBIRD_FLAG } from "@posthog/shared";
import type { ChannelsSurface } from "@posthog/shared/analytics-events";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useFileCanvas } from "@posthog/ui/features/canvas/hooks/useFileCanvas";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import {
  type MenuFlyoutItem,
  MenuSubFlyout,
  SearchableMenuFlyout,
} from "@posthog/ui/primitives/SearchableMenuFlyout";

/**
 * A "File to…" submenu for a canvas, for use inside a quill `DropdownMenu`. Lists
 * the project's spaces, ticks the one the canvas already sits in, and files it on
 * pick. Same searchable flyout the sidebar row's menu uses, so filing behaves the
 * same wherever it appears. Renders nothing while there is no space to file to.
 */
export function CanvasFileToSubmenu({
  dashboardId,
  currentChannelId,
  surface,
  onFiled,
}: {
  dashboardId: string;
  /** The space the canvas is filed under now, ticked in the list. */
  currentChannelId: string;
  surface: ChannelsSurface;
  /**
   * Called with the target space id after a successful file. The canvas header
   * uses it to follow the canvas into its new space; the grid card and sidebar
   * leave it unset and stay put.
   */
  onFiled?: (targetChannelId: string) => void;
}) {
  // "File to…" is a Project Bluebird feature; gate the channel fetch behind the
  // flag so neither the submenu nor its request reaches ungated users.
  const bluebirdEnabled = useFeatureFlag(
    PROJECT_BLUEBIRD_FLAG,
    import.meta.env.DEV,
  );
  const { channels } = useChannels({ enabled: bluebirdEnabled });
  const fileCanvas = useFileCanvas();

  const items: MenuFlyoutItem[] = channels.map((channel) => ({
    id: channel.id,
    label: channel.name,
    current: channel.id === currentChannelId,
    starred: channel.starred,
  }));

  if (items.length === 0) return null;

  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger>
        <FolderSimpleIcon size={14} />
        File to…
      </DropdownMenuSubTrigger>
      <MenuSubFlyout className="w-64 p-0">
        <SearchableMenuFlyout
          items={items}
          placeholder="Search spaces…"
          emptyLabel="No spaces"
          onSelect={(targetChannelId) =>
            void fileCanvas({
              dashboardId,
              sourceChannelId: currentChannelId,
              targetChannelId,
              targetName: channels.find((c) => c.id === targetChannelId)?.name,
              surface,
            }).then((filed) => {
              if (filed) onFiled?.(targetChannelId);
            })
          }
        />
      </MenuSubFlyout>
    </DropdownMenuSub>
  );
}
