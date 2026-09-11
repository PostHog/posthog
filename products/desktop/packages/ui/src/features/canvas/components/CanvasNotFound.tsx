import { LockIcon, MagnifyingGlassIcon } from "@phosphor-icons/react";
import {
  Button,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useProjects } from "@posthog/ui/features/projects/useProjects";
import { CanvasSkeleton } from "@posthog/ui/router/routeSkeletons";
import { Link } from "@tanstack/react-router";

// The API hides a canvas the viewer may not see behind the same 404 as one in
// another project or one that was deleted. The link's channel tells them
// apart: a channel the viewer can see means the canvas is gone, and one they
// cannot means the space is private to them or lives in another project.
export function CanvasNotFound({ channelId }: { channelId?: string }) {
  const { currentProject } = useProjects();
  const { channels, isLoading } = useChannels();
  if (isLoading) {
    return <CanvasSkeleton />;
  }
  const channel = channelId
    ? channels.find((candidate) => candidate.id === channelId)
    : undefined;
  return (
    <CanvasNotFoundView projectName={currentProject?.name} channel={channel} />
  );
}

export function CanvasNotFoundView({
  projectName,
  channel,
}: {
  projectName?: string;
  channel?: { id: string; name: string };
}) {
  if (channel) {
    return (
      <Empty className="h-full border-0">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <MagnifyingGlassIcon size={24} />
          </EmptyMedia>
          <EmptyTitle>Canvas not found</EmptyTitle>
          <EmptyDescription>
            Couldn't find this canvas in {channel.name}. It may have been
            deleted.
          </EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button
            variant="outline"
            size="default"
            render={
              <Link
                to="/spaces/$channelId"
                params={{ channelId: channel.id }}
              />
            }
          >
            Back to {channel.name}
          </Button>
        </EmptyContent>
      </Empty>
    );
  }

  const where = projectName ?? "this project";
  return (
    <Empty className="h-full border-0">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <LockIcon size={24} />
        </EmptyMedia>
        <EmptyTitle>Can't open this canvas</EmptyTitle>
        <EmptyDescription>
          You don't have access to this canvas, or it isn't in {where}. Ask
          whoever shared it to add you to its space, or switch to the project it
          belongs to and open the link again.
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button variant="outline" size="default" render={<Link to="/spaces" />}>
          Go to spaces
        </Button>
      </EmptyContent>
    </Empty>
  );
}
