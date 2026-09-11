import { MagnifyingGlassIcon } from "@phosphor-icons/react";
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
import { Link } from "@tanstack/react-router";

export function CanvasNotFound({ channelId }: { channelId?: string }) {
  const { currentProject } = useProjects();
  const { channels } = useChannels();
  // The channel lives in the same project as the canvas, so a link from
  // another project names one that is not here either.
  const channel = channelId
    ? channels.find((candidate) => candidate.id === channelId)
    : undefined;
  const where = currentProject ? currentProject.name : "the current project";

  return (
    <Empty className="h-full border-0">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <MagnifyingGlassIcon size={24} />
        </EmptyMedia>
        <EmptyTitle>Canvas not found</EmptyTitle>
        <EmptyDescription>
          Couldn't find this canvas in {where}. If it belongs to another
          project, switch to that project and open the link again.
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        {channel ? (
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
        ) : (
          <Button
            variant="outline"
            size="default"
            render={<Link to="/spaces" />}
          >
            Go to spaces
          </Button>
        )}
      </EmptyContent>
    </Empty>
  );
}
