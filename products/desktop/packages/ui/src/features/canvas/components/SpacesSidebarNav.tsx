import {
  CaretRightIcon,
  CubeIcon,
  HouseIcon,
  ListChecks,
  PlusIcon,
  Robot,
  Tray,
} from "@phosphor-icons/react";
import {
  Autocomplete,
  AutocompleteInput,
  AutocompleteItem,
  AutocompleteList,
  Button,
  cn,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Separator,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { CreateChannelModal } from "@posthog/ui/features/canvas/components/CreateChannelModal";
import { SpaceSection } from "@posthog/ui/features/canvas/components/SpaceSection";
import { useChannelStarMutations } from "@posthog/ui/features/canvas/hooks/useChannelStars";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useStarredChannelSlots } from "@posthog/ui/features/canvas/hooks/useStarredChannelSlots";
import { PERSONAL_CHANNEL_NAME } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useSpacesSidebarStore } from "@posthog/ui/features/canvas/stores/spacesSidebarStore";
import { useInboxAllReports } from "@posthog/ui/features/inbox/hooks/useInboxAllReports";
import { CountBadge } from "@posthog/ui/primitives/CountBadge";
import { toast } from "@posthog/ui/primitives/toast";
import {
  navigateToCode,
  navigateToInbox,
} from "@posthog/ui/router/navigationBridge";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { track } from "@posthog/ui/shell/analytics";
import { useRouterState } from "@tanstack/react-router";
import { useState } from "react";

/**
 * The static spaces nav: Home / Tasks / Inbox, then every starred space with
 * its tasks expanded inline beneath it, then "Add space" (star an existing
 * space or create a new one) and the pinned-agents section. Replaces the
 * panes slider under `code-spaces-layout`.
 */
export function SpacesSidebarNav() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const isHome =
    pathname === "/code" || pathname === "/code/" || pathname === "/";
  const isTasks =
    pathname.startsWith("/code/tasks") || pathname.startsWith("/website");
  const isInbox =
    pathname.startsWith("/code/inbox") || pathname.startsWith("/inbox");

  const { slots: pinnedSpaces } = useStarredChannelSlots();
  const { star } = useChannelStarMutations();
  const { channels } = useChannels();
  const { counts } = useInboxAllReports({
    ignoreFilters: true,
    refetchIntervalMs: 60_000,
  });

  const openAgents = useSpacesSidebarStore((s) => s.openAgents);
  const toggleAgents = useSpacesSidebarStore((s) => s.toggleAgents);

  const [addOpen, setAddOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);

  // The list is every channel not already pinned; the personal channel isn't a
  // thing you pin to this list.
  const addable = channels.filter(
    (c) =>
      c.name !== PERSONAL_CHANNEL_NAME &&
      !pinnedSpaces.some((p) => p.id === c.id),
  );

  const addExisting = (channelId: string | null) => {
    if (!channelId) return;
    const channel = channels.find((c) => c.id === channelId);
    if (!channel) return;
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "star",
      surface: "sidebar",
      channel_id: channel.id,
    });
    star(channel).catch((error: unknown) =>
      toast.error("Couldn't add space", {
        description: error instanceof Error ? error.message : String(error),
      }),
    );
    useSpacesSidebarStore.getState().setOpen(channel.id, true);
    setAddOpen(false);
  };

  return (
    <>
      {/* Nav: Home / Tasks / Inbox */}
      <div className="flex shrink-0 flex-col gap-px px-2 pt-1">
        <Button
          variant="default"
          size="default"
          left
          data-selected={isHome || undefined}
          className="w-full min-w-0 justify-start gap-2 text-muted-foreground data-selected:bg-fill-selected data-selected:text-foreground"
          onClick={() => navigateToCode()}
        >
          <span className="flex h-[18px] w-[18px] shrink-0 items-center justify-center">
            <HouseIcon size={16} weight={isHome ? "fill" : "regular"} />
          </span>
          <span className="truncate font-medium text-[13px]">Home</span>
        </Button>
        <Button
          variant="default"
          size="default"
          left
          data-selected={isTasks || undefined}
          className="w-full min-w-0 justify-start gap-2 text-muted-foreground data-selected:bg-fill-selected data-selected:text-foreground"
          onClick={() => navigateToCode()}
        >
          <span className="flex h-[18px] w-[18px] shrink-0 items-center justify-center">
            <ListChecks size={16} weight={isTasks ? "fill" : "regular"} />
          </span>
          <span className="truncate font-medium text-[13px]">Tasks</span>
        </Button>

        {/* Inbox, with "+" and chevron affordances on hover */}
        <div className="group/inbox flex w-full items-center">
          <Button
            variant="default"
            size="default"
            left
            data-selected={isInbox || undefined}
            className="min-w-0 flex-1 justify-start gap-2 text-muted-foreground data-selected:bg-fill-selected data-selected:text-foreground"
            onClick={() => navigateToInbox()}
          >
            <span className="flex h-[18px] w-[18px] shrink-0 items-center justify-center">
              <Tray size={16} weight={isInbox ? "fill" : "regular"} />
            </span>
            <span className="truncate font-medium text-[13px]">Inbox</span>
            <CountBadge count={counts.pulls} className="ml-1" />
          </Button>
          <span className="flex shrink-0 items-center gap-0.5 pr-1">
            <button
              type="button"
              aria-label="New task"
              className="flex h-5 w-5 items-center justify-center rounded text-gray-10 opacity-0 transition-opacity hover:bg-gray-4 focus:opacity-100 group-hover/inbox:opacity-100"
              onClick={() => {
                track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
                  action_type: "new_task_open",
                  surface: "sidebar",
                });
                openTaskInput();
              }}
            >
              <PlusIcon size={12} />
            </button>
            <button
              type="button"
              aria-label="Inbox menu"
              className="flex h-5 w-5 items-center justify-center rounded text-gray-10 opacity-0 transition-opacity hover:bg-gray-4 focus:opacity-100 group-hover/inbox:opacity-100"
              onClick={() => navigateToInbox()}
            >
              <CaretRightIcon size={12} />
            </button>
          </span>
        </div>
      </div>

      {/* Pinned spaces */}
      <div className="flex flex-col gap-px px-2 pt-1">
        {pinnedSpaces.map((space) => (
          <SpaceSection key={space.id} channel={space} />
        ))}

        {/* Add space */}
        <Popover open={addOpen} onOpenChange={setAddOpen}>
          <PopoverTrigger
            render={
              <Button
                variant="default"
                size="default"
                left
                className="w-full min-w-0 justify-start gap-2 text-muted-foreground"
              />
            }
          >
            <span className="flex h-[18px] w-[18px] shrink-0 items-center justify-center">
              <PlusIcon size={14} />
            </span>
            <span className="truncate font-medium text-[13px]">Add space</span>
          </PopoverTrigger>
          <PopoverContent align="start" side="bottom" className="w-72 p-0">
            <Autocomplete
              open
              inline
              items={addable.map((c) => c.id)}
              onValueChange={(value) => addExisting(value ?? null)}
            >
              <div className="p-1.5">
                <AutocompleteInput
                  placeholder="Find and add any existing spaces"
                  aria-label="Find and add any existing spaces"
                  className="h-8 text-[13px]"
                />
              </div>
              <AutocompleteList className="max-h-56">
                {addable.length === 0 && (
                  <div className="px-3 py-2 text-[13px] text-muted-foreground">
                    No more spaces to add.
                  </div>
                )}
                {addable.map((c) => (
                  <AutocompleteItem key={c.id} value={c.id}>
                    <span className="flex h-[18px] w-[18px] items-center justify-center text-muted-foreground">
                      <CubeIcon size={14} />
                    </span>
                    <span className="truncate">{c.name}</span>
                  </AutocompleteItem>
                ))}
              </AutocompleteList>
            </Autocomplete>
            <Separator />
            <div className="p-1.5">
              <Button
                variant="default"
                size="default"
                left
                className="w-full justify-start gap-2"
                onClick={() => {
                  setAddOpen(false);
                  setCreateOpen(true);
                }}
              >
                <CubeIcon size={14} />
                New space
              </Button>
            </div>
          </PopoverContent>
        </Popover>
      </div>

      {/* Pinned agents (prototype placeholder) */}
      <div className="mt-0.5 flex flex-col gap-px px-2 pt-1">
        <div className="group/agents flex w-full items-center">
          <Button
            variant="default"
            size="default"
            left
            className="min-w-0 flex-1 justify-start gap-2 text-muted-foreground"
            onClick={toggleAgents}
            aria-expanded={openAgents}
          >
            <CaretRightIcon
              size={12}
              className={cn(
                "shrink-0 text-muted-foreground transition-transform",
                openAgents && "rotate-90",
              )}
            />
            <span className="flex h-[18px] w-[18px] shrink-0 items-center justify-center">
              <Robot size={16} />
            </span>
            <span className="truncate font-medium text-[13px]">Agents</span>
          </Button>
          <span className="flex shrink-0 items-center pr-1">
            <button
              type="button"
              aria-label="Add agent"
              className="flex h-5 w-5 items-center justify-center rounded text-gray-10 opacity-0 transition-opacity hover:bg-gray-4 focus:opacity-100 group-hover/agents:opacity-100"
              onClick={() =>
                track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
                  action_type: "star",
                  surface: "sidebar",
                })
              }
            >
              <PlusIcon size={12} />
            </button>
          </span>
        </div>
        {openAgents && (
          <div className="px-3 py-2 pl-7 text-[12px] text-muted-foreground">
            Agents you pin will show here.
          </div>
        )}
      </div>

      <CreateChannelModal open={createOpen} onOpenChange={setCreateOpen} />
    </>
  );
}
