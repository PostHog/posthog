import { CaretDown, Check } from "@phosphor-icons/react";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@posthog/quill";
import { channelGlyph } from "@posthog/ui/features/canvas/components/channelGlyph";
import { useChannelStars } from "@posthog/ui/features/canvas/hooks/useChannelStars";
import {
  type Channel,
  useChannels,
} from "@posthog/ui/features/canvas/hooks/useChannels";
import { PERSONAL_CHANNEL_NAME } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useSpacesSidebarStore } from "@posthog/ui/features/canvas/stores/spacesSidebarStore";
import { useMemo } from "react";

/**
 * Which space a new task files into — a chip for the composer's selector row,
 * drawn exactly like WorkspaceModeSelect ("Cloud"/"Local") beside it. The menu
 * leads with the starred spaces in their sidebar order (#me first), a
 * separator, then everything else alphabetically — items in the flyout
 * vocabulary the switchers use: a leading check well, then the space's own
 * glyph (only #me carries one), then the name.
 */
export function SpaceSelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (channelId: string) => void;
}) {
  const { channels } = useChannels();
  const { starredRefToShortcutId } = useChannelStars();
  const spaceOrder = useSpacesSidebarStore((s) => s.spaceOrder);
  const current = channels.find((c) => c.id === value);

  const { starred, rest } = useMemo(() => {
    const me = channels.filter((c) => c.name === PERSONAL_CHANNEL_NAME);
    const rank = new Map(spaceOrder.map((id, index) => [id, index]));
    const starredList = channels
      .filter(
        (c) =>
          c.name !== PERSONAL_CHANNEL_NAME &&
          starredRefToShortcutId.has(c.path),
      )
      .sort(
        (a, b) =>
          (rank.get(a.id) ?? Number.MAX_SAFE_INTEGER) -
          (rank.get(b.id) ?? Number.MAX_SAFE_INTEGER),
      );
    const starredIds = new Set(starredList.map((c) => c.id));
    return {
      starred: [...me, ...starredList],
      rest: channels
        .filter(
          (c) => c.name !== PERSONAL_CHANNEL_NAME && !starredIds.has(c.id),
        )
        .sort((a, b) => a.name.localeCompare(b.name)),
    };
  }, [channels, starredRefToShortcutId, spaceOrder]);

  const triggerGlyph = channelGlyph(current?.name, { size: 14, space: true });

  const renderItem = (space: Channel) => {
    const glyph = channelGlyph(space.name, { size: 14, space: true });
    return (
      <DropdownMenuItem
        key={space.id}
        className="justify-start"
        onClick={() => {
          if (space.id !== value) onChange(space.id);
        }}
      >
        <span className="flex w-4 shrink-0 items-center justify-center">
          {space.id === value && <Check size={14} className="text-accent-11" />}
        </span>
        {glyph && (
          <span className="flex shrink-0 items-center text-muted-foreground">
            {glyph}
          </span>
        )}
        <span className="min-w-0 truncate text-[13px]">{space.name}</span>
      </DropdownMenuItem>
    );
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button type="button" variant="outline" size="sm" aria-label="Space">
            {triggerGlyph && (
              <span className="text-muted-foreground">{triggerGlyph}</span>
            )}
            {current?.name ?? "Space"}
            <CaretDown
              size={10}
              weight="bold"
              className="text-muted-foreground"
            />
          </Button>
        }
      />
      <DropdownMenuContent
        align="start"
        side="bottom"
        sideOffset={6}
        className="w-auto min-w-[200px]"
      >
        {starred.map(renderItem)}
        {starred.length > 0 && rest.length > 0 && <DropdownMenuSeparator />}
        {rest.map(renderItem)}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
