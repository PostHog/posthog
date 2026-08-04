import {
  CaretDown,
  CheckIcon,
  CubeFocusIcon,
  LockSimpleIcon,
} from "@phosphor-icons/react";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@posthog/quill";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { PERSONAL_CHANNEL_NAME } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useMemo } from "react";

function spaceIcon(name: string | undefined) {
  return name === PERSONAL_CHANNEL_NAME ? (
    <LockSimpleIcon size={14} weight="regular" />
  ) : (
    <CubeFocusIcon size={14} weight="regular" />
  );
}

/**
 * Which space a new task files into — a chip for the composer's selector row,
 * drawn exactly like WorkspaceModeSelect ("Cloud"/"Local") beside it.
 * Personal space first, the rest alphabetical.
 */
export function SpaceSelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (channelId: string) => void;
}) {
  const { channels } = useChannels();
  const current = channels.find((c) => c.id === value);

  const options = useMemo(
    () =>
      [...channels].sort((a, b) => {
        if (a.name === PERSONAL_CHANNEL_NAME) return -1;
        if (b.name === PERSONAL_CHANNEL_NAME) return 1;
        return a.name.localeCompare(b.name);
      }),
    [channels],
  );

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button type="button" variant="outline" size="sm" aria-label="Space">
            <span className="text-muted-foreground">
              {spaceIcon(current?.name)}
            </span>
            {current?.name ?? "Space"}
            <CaretDown
              size={10}
              weight="bold"
              className="text-muted-foreground"
            />
          </Button>
        }
      />
      <DropdownMenuContent align="start" side="bottom" sideOffset={6}>
        {options.map((space) => (
          <DropdownMenuItem
            key={space.id}
            onClick={() => {
              if (space.id !== value) onChange(space.id);
            }}
          >
            <span className="text-muted-foreground">
              {spaceIcon(space.name)}
            </span>
            <span className="min-w-0 flex-1 truncate">{space.name}</span>
            {space.id === value && <CheckIcon size={14} />}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
