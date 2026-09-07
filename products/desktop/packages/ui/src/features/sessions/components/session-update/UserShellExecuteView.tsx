import type { UserShellExecuteResult } from "@posthog/shared";
import { Box } from "@radix-ui/themes";
import { memo } from "react";
import { ExecuteToolView } from "./ExecuteToolView";

export interface UserShellExecute {
  type: "user_shell_execute";
  id: string;
  command: string;
  cwd: string;
  result?: UserShellExecuteResult;
}

interface UserShellExecuteViewProps {
  item: UserShellExecute;
}

export const UserShellExecuteView = memo(function UserShellExecuteView({
  item,
}: UserShellExecuteViewProps) {
  const isInProgress = !item.result;
  const status = isInProgress ? "in_progress" : "completed";
  const output = item.result
    ? item.result.stdout || item.result.stderr || ""
    : "";

  return (
    <Box className="border-accent-9 border-l-2 pl-2">
      <ExecuteToolView
        toolCall={{
          toolCallId: item.id,
          title: item.command,
          kind: "execute",
          status,
          rawInput: { command: item.command, description: "" },
          content: output
            ? [{ type: "content", content: { type: "text", text: output } }]
            : [],
        }}
        expanded={true}
      />
    </Box>
  );
});
