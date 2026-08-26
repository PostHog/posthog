import {
  BlueprintIcon,
  CaretDownIcon,
  FunnelSimpleIcon,
  MagnifyingGlassIcon,
  RowsIcon,
  SquaresFourIcon,
} from "@phosphor-icons/react";
import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";
import {
  Button,
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
  ComboboxTrigger,
  cn,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Field,
  FieldLabel,
  Input,
  MenuLabel,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Spinner,
} from "@posthog/quill";
import { formatRelativeTimeShort } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useMeQuery } from "@posthog/ui/features/auth/useMeQuery";
import {
  buildCanvasCreatorOptions,
  type CanvasCreatorOption,
} from "@posthog/ui/features/canvas/components/canvasCreatorOptions";
import { iconForTemplate } from "@posthog/ui/features/canvas/components/canvasTemplateIcon";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useAllCanvases } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { track } from "@posthog/ui/shell/analytics";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { Fragment, useId, useMemo, useRef, useState } from "react";

function CanvasFilterCombobox({
  label,
  value,
  options,
  onChange,
  searchPlaceholder,
  emptyLabel,
}: {
  label: string;
  value: string;
  options: readonly CanvasCreatorOption[];
  onChange: (value: string) => void;
  searchPlaceholder: string;
  emptyLabel: string;
}) {
  const id = useId();
  const anchorRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const selected = options.find((option) => option.value === value) ?? null;
  const normalizedSearch = search.trim().toLowerCase();
  const filteredOptions = normalizedSearch
    ? options.filter((option) =>
        `${option.label} ${option.searchLabel ?? ""}`
          .toLowerCase()
          .includes(normalizedSearch),
      )
    : options;

  return (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Combobox<CanvasCreatorOption>
        items={filteredOptions}
        value={selected}
        onValueChange={(option) => {
          if (option) onChange(option.value);
        }}
        itemToStringLabel={(option) => option.label}
        itemToStringValue={(option) => option.value}
        open={open}
        onOpenChange={(nextOpen) => {
          setOpen(nextOpen);
          setSearch("");
        }}
        inputValue={search}
        onInputValueChange={(nextSearch) => setSearch(nextSearch ?? "")}
        filter={null}
        autoHighlight
      >
        <div ref={anchorRef}>
          <ComboboxTrigger
            render={
              <Button
                id={id}
                type="button"
                variant="outline"
                size="sm"
                className="w-full justify-between"
                aria-label={`${label}: ${selected?.label ?? "None"}`}
              >
                <span className="min-w-0 truncate text-left">
                  {selected?.label}
                </span>
                <CaretDownIcon className="shrink-0" />
              </Button>
            }
          />
        </div>
        <ComboboxContent
          anchor={anchorRef}
          side="bottom"
          sideOffset={4}
          align="start"
          className="w-[var(--anchor-width)]"
        >
          <ComboboxInput placeholder={searchPlaceholder} showTrigger={false} />
          <ComboboxEmpty>{emptyLabel}</ComboboxEmpty>
          <ComboboxList className="max-h-[min(18rem,calc(var(--available-height,18rem)-5rem))]">
            {(option: CanvasCreatorOption) => (
              <ComboboxItem
                key={option.value || "all"}
                value={option}
                title={option.label}
              >
                {option.label}
              </ComboboxItem>
            )}
          </ComboboxList>
        </ComboboxContent>
      </Combobox>
    </Field>
  );
}

export function CanvasesPane({ className }: { className?: string }) {
  const { dashboards, isLoading } = useAllCanvases();
  const { channels } = useChannels();
  const { data: currentUser } = useMeQuery();
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
  const spaceOptions = useMemo<CanvasCreatorOption[]>(
    () => [
      { value: "", label: "Every space" },
      ...channels.map((channel) => ({
        value: channel.id,
        label: channelNames.get(channel.id) ?? channel.name,
      })),
    ],
    [channelNames, channels],
  );
  const creatorOptions = useMemo(
    () =>
      buildCanvasCreatorOptions(
        dashboards,
        currentUser
          ? { uuid: currentUser.uuid, name: userDisplayName(currentUser) }
          : undefined,
      ),
    [currentUser, dashboards],
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
          <Popover>
            <PopoverTrigger
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
            <PopoverContent
              align="end"
              side="bottom"
              sideOffset={6}
              className="w-64"
              aria-label="Filter canvases"
            >
              <CanvasFilterCombobox
                label="Space"
                value={spaceId}
                onChange={setSpaceId}
                options={spaceOptions}
                searchPlaceholder="Search spaces…"
                emptyLabel="No spaces found."
              />
              <CanvasFilterCombobox
                label="Created by"
                value={creatorUuid}
                onChange={setCreatorUuid}
                options={creatorOptions}
                searchPlaceholder="Search people…"
                emptyLabel="No people found."
              />
            </PopoverContent>
          </Popover>
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
