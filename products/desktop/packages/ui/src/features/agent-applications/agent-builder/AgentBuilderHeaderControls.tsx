import { SidebarSimpleIcon, SparkleIcon } from "@phosphor-icons/react";
import {
  Button,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { Flex } from "@radix-ui/themes";
import { AGENT_PLATFORM_FLAG } from "../featureFlag";
import { headerActionForPage } from "./agentBuilderActions";
import { useAgentBuilderStore } from "./agentBuilderStore";

/**
 * The agents-header control cluster — identical across every agents view.
 *
 * Pinned absolutely to the top-right of the nearest `relative` ancestor so it
 * sits on the same row as the Agent Builder dock header (matching `py-2`),
 * keeping the two halves of the agents UI visually aligned across views.
 *
 * One split button is the single entry point into the Agent Builder dock:
 *  - the primary segment is the contextual "edit with AI" action for the view
 *    you're on (New agent / Edit configuration / Explain this session / …) — it
 *    opens the dock and seeds the matching prompt,
 *  - the trailing segment just opens the dock without seeding, so you can peek
 *    at the existing conversation; once the dock is open it disappears so we
 *    don't double up with the dock's own close button.
 * Views with no obvious action (Scouts) collapse to the lone open toggle.
 * Renders nothing unless the `agent-platform` flag is on.
 */
export function AgentBuilderHeaderControls() {
  const enabled = useFeatureFlag(AGENT_PLATFORM_FLAG);
  const visible = useAgentBuilderStore((s) => s.visible);
  const page = useAgentBuilderStore((s) => s.page);
  const toggleVisible = useAgentBuilderStore((s) => s.toggleVisible);
  const startAgentBuilder = useAgentBuilderStore((s) => s.startAgentBuilder);

  if (!enabled) return null;

  const action = headerActionForPage(page);
  const openTip = "Open the agent builder (⌘⇧I)";

  return (
    <TooltipProvider delay={500}>
      <Flex
        align="center"
        gap="2"
        className="absolute top-0 right-0 z-10 shrink-0 px-6 py-2"
      >
        {action ? (
          <div className="flex items-center">
            <Tooltip>
              <TooltipTrigger
                render={
                  <Button
                    variant="outline"
                    size="sm"
                    className={
                      visible
                        ? "rounded-[3px]"
                        : "rounded-s-[3px] rounded-e-none"
                    }
                    onClick={() =>
                      startAgentBuilder(action.prompt, action.agentSlug)
                    }
                  >
                    <SparkleIcon
                      size={14}
                      weight="fill"
                      className="text-(--accent-9)"
                    />
                    {action.label}
                  </Button>
                }
              />
              <TooltipContent side="top">
                Open the agent builder and start here
              </TooltipContent>
            </Tooltip>
            {visible ? null : (
              <Tooltip>
                <TooltipTrigger
                  render={
                    <Button
                      variant="outline"
                      size="icon-sm"
                      className="rounded-s-none rounded-e-[3px] border-s-0"
                      aria-label={openTip}
                      onClick={toggleVisible}
                    >
                      <SidebarSimpleIcon size={14} weight="regular" />
                    </Button>
                  }
                />
                <TooltipContent side="top">{openTip}</TooltipContent>
              </Tooltip>
            )}
          </div>
        ) : visible ? null : (
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  variant="outline"
                  size="icon-sm"
                  aria-label={openTip}
                  onClick={toggleVisible}
                >
                  <SparkleIcon
                    size={14}
                    weight="fill"
                    className="text-(--accent-9)"
                  />
                </Button>
              }
            />
            <TooltipContent side="top">{openTip}</TooltipContent>
          </Tooltip>
        )}
      </Flex>
    </TooltipProvider>
  );
}
