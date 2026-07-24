import type { PermissionOption } from "@agentclientprotocol/sdk";
import { readMcpToolName } from "@posthog/shared";
import { DefaultPermission } from "./DefaultPermission";
import { DeletePermission } from "./DeletePermission";
import { EditPermission } from "./EditPermission";
import { ExecutePermission } from "./ExecutePermission";
import { FetchPermission } from "./FetchPermission";
import { McpPermission } from "./McpPermission";
import { MovePermission } from "./MovePermission";
import { QuestionPermission } from "./QuestionPermission";
import { ReadPermission } from "./ReadPermission";
import { SearchPermission } from "./SearchPermission";
import { SwitchModePermission } from "./SwitchModePermission";
import { ThinkPermission } from "./ThinkPermission";
import type { PermissionToolCall } from "./types";

interface PermissionSelectorProps {
  toolCall: PermissionToolCall;
  options: PermissionOption[];
  onSelect: (
    optionId: string,
    customInput?: string,
    answers?: Record<string, string>,
  ) => void;
  onCancel: () => void;
}

export function PermissionSelector({
  toolCall,
  options,
  onSelect,
  onCancel,
}: PermissionSelectorProps) {
  const props = { toolCall, options, onSelect, onCancel };
  const meta = toolCall._meta as { codeToolKind?: string } | undefined;
  if (readMcpToolName(toolCall._meta)) {
    return <McpPermission {...props} />;
  }
  const kind = meta?.codeToolKind ?? (toolCall.kind as string);

  switch (kind) {
    case "execute":
      return <ExecutePermission {...props} />;
    case "edit":
      return <EditPermission {...props} />;
    case "read":
      return <ReadPermission {...props} />;
    case "delete":
      return <DeletePermission {...props} />;
    case "move":
      return <MovePermission {...props} />;
    case "search":
      return <SearchPermission {...props} />;
    case "fetch":
      return <FetchPermission {...props} />;
    case "think":
      return <ThinkPermission {...props} />;
    case "switch_mode":
      return <SwitchModePermission {...props} />;
    case "question":
      return <QuestionPermission {...props} />;
    default:
      return <DefaultPermission {...props} />;
  }
}
