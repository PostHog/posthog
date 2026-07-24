import { FileTextIcon, HashIcon, PlusIcon } from "@phosphor-icons/react";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { CreateChannelModal } from "@posthog/ui/features/canvas/components/CreateChannelModal";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { useRouterState } from "@tanstack/react-router";
import { useState } from "react";

// The create affordance for the Channels space, floated over the bottom-right
// of the channel list. It owns the create-channel modal (the list itself has no
// other entry point) and opens its menu upward, since it sits at the bottom.
export function ChannelsFab() {
  const [modalOpen, setModalOpen] = useState(false);
  // New task has no /website mirror yet, so it jumps back to Code unless we're
  // already in the Channels space — same rule as the nav's New task row.
  const inChannels = useRouterState({
    select: (s) => s.location.pathname.startsWith("/website"),
  });

  return (
    <>
      <DropdownMenu>
        <Tooltip>
          <TooltipTrigger
            render={
              <DropdownMenuTrigger
                render={
                  <Button
                    variant="primary"
                    size="icon-lg"
                    aria-label="Create"
                    className="absolute right-3 bottom-3 z-10 rounded-full shadow-lg"
                  >
                    <PlusIcon size={20} weight="bold" />
                  </Button>
                }
              />
            }
          />
          <TooltipContent side="top" align="center">
            Create something new
          </TooltipContent>
        </Tooltip>
        <DropdownMenuContent align="center" side="top" sideOffset={6}>
          <DropdownMenuItem onClick={() => setModalOpen(true)}>
            <HashIcon size={14} className="text-gray-9" />
            New channel
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() =>
              openTaskInput(inChannels ? { space: "website" } : undefined)
            }
          >
            <FileTextIcon size={14} className="text-gray-9" />
            New task
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <CreateChannelModal open={modalOpen} onOpenChange={setModalOpen} />
    </>
  );
}
