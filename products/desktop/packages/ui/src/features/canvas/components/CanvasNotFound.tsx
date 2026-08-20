import { MagnifyingGlassIcon } from "@phosphor-icons/react";
import { flattenProjectIds } from "@posthog/core/auth/schemas";
import {
  Button,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useSelectProjectMutation } from "@posthog/ui/features/auth/useAuthMutations";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useCanvasLocation } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useProjects } from "@posthog/ui/features/projects/useProjects";
import { navigateToChannelDashboard } from "@posthog/ui/router/navigationBridge";
import { Link } from "@tanstack/react-router";

/**
 * Shown when a canvas id resolves to nothing in the signed-in project.
 *
 * A share link carries only the channel and canvas ids, but the record is fetched from
 * `/api/projects/<currentProjectId>/canvases/<id>/`, so a link to a canvas in another project
 * 404s here. That 404 used to render as the generic empty-canvas state, which reads as "this
 * canvas exists and has nothing in it" and sends people looking for the wrong problem.
 */
export function CanvasNotFound({
  channelId,
  dashboardId,
}: {
  channelId?: string;
  dashboardId?: string;
}) {
  const { currentProject } = useProjects();
  const { channels } = useChannels();
  const { location, isFetching } = useCanvasLocation(dashboardId, {
    enabled: true,
  });
  const orgProjectsMap = useAuthStateValue((state) => state.orgProjectsMap);
  const selectProject = useSelectProjectMutation();

  // The channel belongs to the same project as the canvas, so a link from elsewhere names one
  // that isn't here either. Offering to go "back" to it would be a second dead end.
  const channel = channelId
    ? channels.find((candidate) => candidate.id === channelId)
    : undefined;
  // A session granted only one project cannot switch into another, so it is told to sign in
  // again rather than offered a button that would fail.
  const switchable =
    location != null &&
    flattenProjectIds(orgProjectsMap).includes(location.projectId);

  const switchAndOpen = async () => {
    if (!location) return;
    await selectProject.mutateAsync(location.projectId);
    // After the await on purpose. Selecting a project runs onProjectSelected, which calls
    // openTaskInput() and navigates away; mutateAsync resolves once that has run, so this
    // navigation lands last. The channel id comes from the location, not the dead route.
    navigateToChannelDashboard(location.channelId, location.canvasId);
  };

  return (
    <Empty className="h-full border-0">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <MagnifyingGlassIcon size={24} />
        </EmptyMedia>
        <EmptyTitle>
          {location ? "This canvas is in another project" : "Canvas not found"}
        </EmptyTitle>
        <EmptyDescription>{describe()}</EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        {switchable && (
          <Button
            variant="primary"
            size="default"
            loading={selectProject.isPending}
            disabled={selectProject.isPending}
            onClick={() => void switchAndOpen()}
          >
            Switch to {location.projectName}
          </Button>
        )}
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

  function describe(): string {
    if (location && switchable) {
      return `"${location.canvasName}" is in ${location.organizationName} / ${location.projectName}.`;
    }
    if (location) {
      return `"${location.canvasName}" is in ${location.organizationName} / ${location.projectName}. This app is signed in to ${currentProject?.name ?? "another project"}. Sign in again and pick that project to open it here.`;
    }
    if (isFetching) {
      return "Looking for this canvas in your other projects.";
    }
    return currentProject
      ? `This canvas is not in ${currentProject.name}. Switch to the project it belongs to and open the link again.`
      : "This canvas is not in the project you are signed in to. Switch to the project it belongs to and open the link again.";
  }
}
