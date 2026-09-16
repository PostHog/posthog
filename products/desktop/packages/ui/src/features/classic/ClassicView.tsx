import { ArrowClockwiseIcon, SquaresFourIcon } from "@phosphor-icons/react";
import { useServiceOptional } from "@posthog/di/react";
import {
  Button,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@posthog/quill";
import { getCloudUrlFromRegion } from "@posthog/shared";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useMeQuery } from "@posthog/ui/features/auth/useMeQuery";
import { ChromeBar } from "@posthog/ui/primitives/ChromeBar";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";
import { type ReactElement, useState } from "react";
import {
  CLASSIC_FRAME_COMPONENT,
  type ClassicFrameComponent,
  type ClassicFrameStatus,
} from "./classicFrameHost";
import { useClassicViewStore } from "./classicViewStore";

export function ClassicContent({
  Frame,
  url,
  accountId,
}: {
  Frame: ClassicFrameComponent;
  url: string;
  accountId: string;
}): ReactElement {
  const [status, setStatus] = useState<ClassicFrameStatus>("loading");
  const revision = useClassicViewStore((state) => state.revision);
  const openDashboards = useClassicViewStore((state) => state.openDashboards);
  const reload = (): void => {
    setStatus("loading");
    openDashboards();
  };

  return (
    <section
      className="flex h-full min-w-0 flex-col"
      aria-label="Classic dashboards"
    >
      <ChromeBar
        actions={
          <Button
            size="icon"
            aria-label="Reload dashboards"
            onClick={reload}
            disabled={status === "loading"}
          >
            <ArrowClockwiseIcon />
          </Button>
        }
      >
        <SquaresFourIcon className="shrink-0" />
        <Button
          variant="default"
          onClick={reload}
          disabled={status === "loading"}
        >
          Dashboards
        </Button>
        <span className="truncate text-muted-foreground text-xs">
          Classic has its own web sign-in.
        </span>
      </ChromeBar>
      <div className="relative min-h-0 flex-1">
        <Frame
          key={revision}
          url={url}
          accountId={accountId}
          onStatusChange={setStatus}
        />
        {status === "loading" && (
          <div className="absolute inset-0 bg-background">
            <LoadingState label="Loading PostHog" />
          </div>
        )}
        {status === "error" && (
          <div className="absolute inset-0 bg-background">
            <Empty>
              <EmptyHeader>
                <EmptyTitle>PostHog did not load</EmptyTitle>
                <EmptyDescription>
                  Check your connection, then select Reload dashboards.
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          </div>
        )}
      </div>
    </section>
  );
}

export function ClassicView(): ReactElement {
  const Frame = useServiceOptional<ClassicFrameComponent>(
    CLASSIC_FRAME_COMPONENT,
  );
  const region = useAuthStateValue((state) => state.cloudRegion);
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const { data: user } = useMeQuery();

  if (!Frame || (region !== "us" && region !== "eu")) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyTitle>Classic is a desktop preview</EmptyTitle>
          <EmptyDescription>
            Open the desktop app with a US or EU cloud project to use
            dashboards.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }
  if (!projectId || !user) return <LoadingState label="Loading project" />;

  const url = `${getCloudUrlFromRegion(region)}/project/${projectId}/dashboards`;
  return (
    <ClassicContent
      key={`${user.uuid}:${url}`}
      Frame={Frame}
      url={url}
      accountId={user.uuid}
    />
  );
}
