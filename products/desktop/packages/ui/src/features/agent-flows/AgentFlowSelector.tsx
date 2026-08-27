import { CaretDownIcon, FlowArrowIcon } from "@phosphor-icons/react";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  MenuLabel,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import type { AgentFlowDefinition } from "@posthog/shared";
import { useNavigate } from "@tanstack/react-router";

const DIRECT_VALUE = "__direct_pi__";

export function AgentFlowSelector({
  flows,
  selectedFlowId,
  disabled,
  disabledReason,
  onChange,
}: {
  flows: AgentFlowDefinition[];
  selectedFlowId: string | null;
  disabled?: boolean;
  /** When set, the trigger is disabled and explains why on hover. */
  disabledReason?: string;
  onChange: (flowId: string | null) => void;
}) {
  const navigate = useNavigate();
  const selectedFlow = flows.find((flow) => flow.id === selectedFlowId);

  const trigger = (
    <Button
      type="button"
      variant="default"
      size="sm"
      disabled={disabled || !!disabledReason}
      aria-label={
        selectedFlow ? `Agent flow: ${selectedFlow.name}` : "Agent flow"
      }
    >
      <FlowArrowIcon size={14} weight="bold" />
      <span className="max-w-40 truncate">{selectedFlow?.name ?? "Flow"}</span>
      <CaretDownIcon size={10} weight="bold" />
    </Button>
  );

  if (disabledReason) {
    return (
      <Tooltip>
        <TooltipTrigger
          render={<span className="inline-flex">{trigger}</span>}
        />
        <TooltipContent>{disabledReason}</TooltipContent>
      </Tooltip>
    );
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={trigger} />
      <DropdownMenuContent
        align="start"
        side="top"
        sideOffset={6}
        className="min-w-[240px]"
      >
        <MenuLabel>Agent flow</MenuLabel>
        <DropdownMenuRadioGroup
          value={selectedFlow?.id ?? DIRECT_VALUE}
          onValueChange={(value) =>
            onChange(value === DIRECT_VALUE ? null : value)
          }
        >
          <DropdownMenuRadioItem value={DIRECT_VALUE}>
            No flow
          </DropdownMenuRadioItem>
          {flows.map((flow) => (
            <DropdownMenuRadioItem key={flow.id} value={flow.id}>
              {flow.name}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => void navigate({ to: "/skills" })}>
          Manage flows
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
