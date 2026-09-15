import type { PermissionOption } from "@agentclientprotocol/sdk";
import { CaretUp, X } from "@phosphor-icons/react";
import { extractPlanText } from "@posthog/core/sessions/planApprovalPresentation";
import {
  Button,
  cn,
  Text,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { PermissionSelector } from "@posthog/ui/features/permissions/PermissionSelector";
import { PlanContent } from "@posthog/ui/features/permissions/PlanContent";
import {
  isPlanPermission,
  readQuestionCount,
} from "@posthog/ui/features/permissions/permissionKind";
import type { PermissionToolCall } from "@posthog/ui/features/permissions/types";
import { useMemo } from "react";

interface ComposerPermissionPanelProps {
  toolCall: PermissionToolCall;
  options: PermissionOption[];
  onSelect: (
    optionId: string,
    customInput?: string,
    answers?: Record<string, string>,
  ) => void;
  onCancel: () => void;
  /** Closes the panel without answering, so the thread can be read again. */
  onClose: () => void;
}

/** What the request asks for, for the chip that opens the panel again. */
function reopenLabel(toolCall: PermissionToolCall): string {
  if (isPlanPermission(toolCall)) return "View plan";
  const questions = readQuestionCount(toolCall);
  return questions > 1 ? `View ${questions} questions` : "View question";
}

/**
 * A plan or a set of choices, docked above the prompt input. The card caps the
 * height, so this fills what the card gives it and scrolls the part that can
 * grow without bound: the plan when there is one, otherwise the option list.
 */
export function ComposerPermissionPanel({
  toolCall,
  options,
  onSelect,
  onCancel,
  onClose,
}: ComposerPermissionPanelProps) {
  const questionCount = useMemo(() => readQuestionCount(toolCall), [toolCall]);
  const planText = useMemo(
    () =>
      isPlanPermission(toolCall)
        ? extractPlanText({
            rawInput: toolCall.rawInput as { plan?: unknown } | null,
            content: toolCall.content,
          })
        : null,
    [toolCall],
  );

  return (
    <div className="flex min-h-0 grow flex-col gap-[2px]">
      <div className="flex shrink-0 items-center justify-end">
        <div className="flex items-center gap-0.5 rounded-sm bg-card py-0.5 pl-1.5">
          {questionCount > 1 && (
            <Text className="text-muted-foreground text-xs">
              {questionCount}
            </Text>
          )}
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  type="button"
                  variant="default"
                  size="icon-xs"
                  aria-label="Close"
                  onClick={onClose}
                >
                  <X size={12} />
                </Button>
              }
            />
            <TooltipContent>Close to read the thread</TooltipContent>
          </Tooltip>
        </div>
      </div>
      {planText && (
        <PlanContent id={toolCall.toolCallId} plan={planText} height="fill" />
      )}
      <div
        className={cn(
          "min-h-0",
          planText ? "shrink-0" : "grow overflow-y-auto",
        )}
      >
        <PermissionSelector
          toolCall={toolCall}
          options={options}
          onSelect={onSelect}
          onCancel={onCancel}
        />
      </div>
    </div>
  );
}

/** Reopens a panel the user closed, for as long as the answer is still due. */
export function ComposerPanelReopenChip({
  toolCall,
  onOpen,
}: {
  toolCall: PermissionToolCall;
  onOpen: () => void;
}) {
  const label = useMemo(() => reopenLabel(toolCall), [toolCall]);

  return (
    <Button type="button" variant="outline" size="xs" onClick={onOpen}>
      <CaretUp size={12} />
      {label}
    </Button>
  );
}
