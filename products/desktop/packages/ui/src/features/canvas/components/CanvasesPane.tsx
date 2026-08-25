import {
  BlueprintIcon,
  FunnelSimpleIcon,
  MagnifyingGlassIcon,
  RowsIcon,
  SquaresFourIcon,
} from "@phosphor-icons/react";
import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";
import {
  Button,
  cn,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Input,
  MenuLabel,
  Spinner,
} from "@posthog/quill";
import { formatRelativeTimeShort } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { iconForTemplate } from "@posthog/ui/features/canvas/components/canvasTemplateIcon";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useAllCanvases } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { track } from "@posthog/ui/shell/analytics";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { Fragment, useMemo, useState } from "react";

function Filter({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger>{label}</DropdownMenuSubTrigger>
      <DropdownMenuSubContent>
        <DropdownMenuRadioGroup value={value} onValueChange={onChange}>
          {options.map((option) => (
            <DropdownMenuRadioItem key={option.value} value={option.value}>
              {option.label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  );
}

export function CanvasesPane({ className }: { className?: string }) {
  const { dashboards, isLoading } = useAllCanvases();
  const { channels } = useChannels();
  const navigate = useNavigate();
  const selectedId = useRouterState({
    select: (state) =>
      (
        state.matches.find((match) => match.fullPath === "/canvases")?.search as
          | { canvas?: string }
          | undefined
      )?.canvas,
  });
  const [query, setQuery] = useState("");
  const [spaceId, setSpaceId] = useState("");
  const [creatorUuid, setCreatorUuid] = useState("");
  const [view, setView] = useState<"list" | "thumbnails">("list");
  const channelNames = useMemo(
    () =>
      new Map(
        channels.map((channel) => [
          channel.id,
          channel.name === "me" ? "personal" : `#${channel.name}`,
        ]),
      ),
    [channels],
  );
  const creators = useMemo(
    () => [
      ...new Map(
        dashboards
          .filter((canvas) => canvas.createdByUuid)
          .map((canvas) => [
            canvas.createdByUuid as string,
            canvas.createdBy ?? "Unknown",
          ]),
      ).entries(),
    ],
    [dashboards],
  );
  const shown = dashboards.filter(
    (canvas) =>
      (!spaceId || canvas.channelId === spaceId) &&
      (!creatorUuid || canvas.createdByUuid === creatorUuid) &&
      (!query ||
        `${canvas.name} ${canvas.description}`
          .toLowerCase()
          .includes(query.toLowerCase())),
  );
  const groups = useMemo(() => {
    const grouped = new Map<string, DashboardRecord[]>();
    for (const canvas of shown)
      grouped.set(canvas.channelId, [
        ...(grouped.get(canvas.channelId) ?? []),
        canvas,
      ]);
    return [...grouped.entries()];
  }, [shown]);
  const open = (canvas: DashboardRecord): void => {
    track(ANALYTICS_EVENTS.DASHBOARD_ACTION, {
      action_type: "open",
      surface: "canvases_pane",
      channel_id: canvas.channelId,
      dashboard_id: canvas.id,
      template_id: canvas.templateId,
    });
    void navigate({ to: "/canvases", search: { canvas: canvas.id } });
  };
  return (
    <div className={cn("flex min-h-0 flex-col", className)}>
      <div className="flex h-10 shrink-0 items-center gap-1 border-border border-b pr-2 pl-3">
        <span className="font-bold text-base">Canvases</span>
        <div className="ml-auto flex gap-1">
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button
                  variant="default"
                  size="icon-xs"
                  aria-label="Filter canvases"
                >
                  <FunnelSimpleIcon size={12} />
                </Button>
              }
            />
            <DropdownMenuContent align="end">
              <Filter
                label="Space"
                value={spaceId}
                onChange={setSpaceId}
                options={[
                  { value: "", label: "Every space" },
                  ...channels.map((channel) => ({
                    value: channel.id,
                    label: channelNames.get(channel.id) ?? channel.name,
                  })),
                ]}
              />
              <Filter
                label="Created by"
                value={creatorUuid}
                onChange={setCreatorUuid}
                options={[
                  { value: "", label: "Anyone" },
                  ...creators.map(([value, label]) => ({ value, label })),
                ]}
              />
            </DropdownMenuContent>
          </DropdownMenu>
          <Button
            variant="default"
            size="icon-xs"
            aria-label="List view"
            data-selected={view === "list" || undefined}
            className="data-selected:bg-fill-selected"
            onClick={() => setView("list")}
          >
            <RowsIcon size={12} />
          </Button>
          <Button
            variant="default"
            size="icon-xs"
            aria-label="Thumbnails view"
            data-selected={view === "thumbnails" || undefined}
            className="data-selected:bg-fill-selected"
            onClick={() => setView("thumbnails")}
          >
            <SquaresFourIcon size={12} />
          </Button>
        </div>
      </div>
      <div className="relative border-border border-b p-1.5">
        <MagnifyingGlassIcon
          size={13}
          className="-translate-y-1/2 pointer-events-none absolute top-1/2 left-3 text-muted-foreground"
        />
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search canvases"
          aria-label="Search canvases"
          className="pl-7"
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
        {isLoading ? (
          <div className="flex justify-center py-10">
            <Spinner />
          </div>
        ) : shown.length === 0 ? (
          <Empty className="border-0 py-8">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <BlueprintIcon />
              </EmptyMedia>
              <EmptyTitle>No canvases match</EmptyTitle>
              <EmptyDescription>Try another search or filter.</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : view === "list" ? (
          <div className="flex flex-col gap-px">
            {groups.map(([channelId, canvases]) => (
              <Fragment key={channelId}>
                <MenuLabel>
                  {channelNames.get(channelId) ?? "Unknown space"}
                </MenuLabel>
                {canvases.map((canvas) => (
                  <Button
                    key={canvas.id}
                    left
                    className={cn(
                      "h-auto w-full py-1.5 text-left",
                      canvas.id === selectedId && "bg-fill-selected",
                    )}
                    onClick={() => open(canvas)}
                  >
                    {iconForTemplate(canvas.templateId, { size: 14 })}
                    <span className="min-w-0">
                      <span className="block truncate text-[13px]">
                        {canvas.name}
                      </span>
                      <span className="block truncate text-muted-foreground text-xxs">
                        {canvas.createdBy ?? "Unknown"} ·{" "}
                        {formatRelativeTimeShort(canvas.updatedAt)}
                      </span>
                    </span>
                  </Button>
                ))}
              </Fragment>
            ))}
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {shown.map((canvas) => (
              <button
                key={canvas.id}
                type="button"
                onClick={() => open(canvas)}
                className={cn(
                  "w-full overflow-hidden rounded-md border border-border bg-background text-left",
                  canvas.id === selectedId && "border-primary bg-fill-selected",
                )}
              >
                <span className="flex h-20 items-center justify-center">
                  {iconForTemplate(canvas.templateId, { size: 24 })}
                </span>
                <span className="block border-border border-t px-2 py-1.5">
                  <span className="block truncate text-[13px]">
                    {canvas.name}
                  </span>
                  <span className="block truncate text-muted-foreground text-xxs">
                    {channelNames.get(canvas.channelId) ?? "Unknown space"}
                  </span>
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
