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

/**
 * Shown when a canvas id resolves to nothing in the signed-in project.
 *
 * A share link carries only the channel and canvas ids, but the record is fetched from
 * `/api/projects/<currentProjectId>/canvases/<id>/`, so a link to a canvas in another project
 * 404s here. That 404 used to render as the generic empty-canvas state, which reads as "this
 * canvas exists and has nothing in it" and sends people looking for the wrong problem.
 */
export function CanvasNotFound({ channelId }: { channelId?: string }) {
  const { currentProject } = useProjects();
  const { channels } = useChannels();
  // The channel belongs to the same project as the canvas, so a link from elsewhere names one
  // that isn't here either. Offering to go "back" to it would be a second dead end.
  const channel = channelId
    ? channels.find((candidate) => candidate.id === channelId)
    : undefined;

  return (
    <Empty className="h-full border-0">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <MagnifyingGlassIcon size={24} />
        </EmptyMedia>
        <EmptyTitle>Canvas not found</EmptyTitle>
        <EmptyDescription>
          {currentProject
            ? `This canvas is not in ${currentProject.name}. Switch to the project it belongs to and open the link again.`
            : "This canvas is not in the project you are signed in to. Switch to the project it belongs to and open the link again."}
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        {channel ? (
          <Button
            variant="outline"
            size="default"
            render={
              <Link
                to="/website/$channelId"
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
            render={<Link to="/website" />}
          >
            Go to spaces
          </Button>
        )}
      </EmptyContent>
    </Empty>
  );
}
