import { PlusIcon, StarIcon } from "@phosphor-icons/react";
import { channelDisplayLabel } from "@posthog/core/canvas/channelName";
import {
  Button,
  Card,
  CardContent,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Skeleton,
  Text,
} from "@posthog/quill";
import { CreateChannelModal } from "@posthog/ui/features/canvas/components/CreateChannelModal";
import { channelGlyph } from "@posthog/ui/features/canvas/components/channelGlyph";
import { SpacesIcon } from "@posthog/ui/features/canvas/components/SpacesIcon";
import {
  type Channel,
  useChannels,
} from "@posthog/ui/features/canvas/hooks/useChannels";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

function SpaceCard({ channel }: { channel: Channel }) {
  const personal = channel.channelType === "personal";

  return (
    <Link
      to="/spaces/$channelId"
      params={{ channelId: channel.id }}
      className="no-underline"
    >
      <Card className="h-full transition-colors hover:bg-fill-hover">
        <CardContent className="flex flex-col gap-2 p-4">
          <div className="flex min-w-0 items-center gap-1.5">
            {channelGlyph(channel.name, { size: 14, personal })}
            <Text weight="semibold" className="truncate">
              {channelDisplayLabel(channel.name, channel.channelType)}
            </Text>
            {channel.starred && (
              <StarIcon
                size={12}
                weight="fill"
                className="shrink-0 text-warning"
              />
            )}
          </div>
          <Text size="sm" variant="muted" className="truncate">
            {channel.repositories.length > 0
              ? channel.repositories.join(", ")
              : "No repositories wired up"}
          </Text>
        </CardContent>
      </Card>
    </Link>
  );
}

/**
 * The `/spaces` page: every space in the project, and a way to make one.
 *
 * A page rather than a redirect to the first space. The rail can put you here,
 * and a destination you cannot rest on is one the rail cannot return you to.
 */
export function SpacesIndex() {
  const { channels, isLoading } = useChannels();
  const [createOpen, setCreateOpen] = useState(false);

  return (
    <div className="h-full overflow-auto bg-gray-1">
      <div className="mx-auto w-full max-w-5xl px-6 py-6">
        <div className="mb-4 flex items-center justify-between gap-3">
          <Text size="lg" weight="semibold">
            Spaces
          </Text>
          <Button variant="primary" onClick={() => setCreateOpen(true)}>
            <PlusIcon size={14} />
            New space…
          </Button>
        </div>

        {isLoading ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-[86px] w-full" />
            ))}
          </div>
        ) : channels.length === 0 ? (
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <SpacesIcon size={20} />
              </EmptyMedia>
              <EmptyTitle>No spaces yet</EmptyTitle>
              <EmptyDescription>
                A space gets its own sessions, canvases, and context.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3">
            {channels.map((channel) => (
              <SpaceCard key={channel.id} channel={channel} />
            ))}
          </div>
        )}
      </div>
      <CreateChannelModal open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  );
}
