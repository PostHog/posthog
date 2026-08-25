import { compactHomePath } from "@posthog/shared";
import { ActionSelector } from "@posthog/ui/primitives/ActionSelector";
import { Box, Code } from "@radix-ui/themes";
import {
  type BasePermissionProps,
  findTextContent,
  toSelectorOptions,
} from "./types";

export function ExecutePermission({
  toolCall,
  options,
  onSelect,
  onCancel,
}: BasePermissionProps) {
  const command = findTextContent(toolCall.content);

  return (
    <ActionSelector
      title={toolCall.title ?? "Execute command"}
      pendingAction={
        command ? (
          <Box className="max-h-[30vh] overflow-auto">
            <Code
              variant="ghost"
              title={command}
              className="whitespace-pre-wrap break-all text-[13px]"
            >
              {compactHomePath(command)}
            </Code>
          </Box>
        ) : undefined
      }
      question="Do you want to proceed?"
      options={toSelectorOptions(options)}
      onSelect={onSelect}
      onCancel={onCancel}
    />
  );
}
