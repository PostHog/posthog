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
} from "@posthog/quill";
import type { AgentFlowDefinition } from "@posthog/shared";
import { useNavigate } from "@tanstack/react-router";

const DIRECT_VALUE = "__direct_pi__";

export function AgentFlowSelector({
  flows,
  selectedFlowId,
  disabled,
  onChange,
}: {
  flows: AgentFlowDefinition[];
  selectedFlowId: string | null;
  disabled?: boolean;
  onChange: (flowId: string | null) => void;
}) {
  const navigate = useNavigate();
  const selectedFlow = flows.find((flow) => flow.id === selectedFlowId);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            type="button"
            variant="default"
            size="sm"
            disabled={disabled}
            aria-label={
              selectedFlow ? `Agent flow: ${selectedFlow.name}` : "Agent flow"
            }
          >
            <FlowArrowIcon size={14} weight="bold" />
            <span className="max-w-40 truncate">
              {selectedFlow?.name ?? "Flow"}
            </span>
            <CaretDownIcon size={10} weight="bold" />
          </Button>
        }
      />
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
        <DropdownMenuItem onClick={() => void navigate({ to: "/flows" })}>
          Manage flows
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
