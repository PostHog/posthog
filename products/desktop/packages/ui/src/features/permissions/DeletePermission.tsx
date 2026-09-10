import { compactHomePath } from "@posthog/shared";
import { ActionSelector } from "@posthog/ui/primitives/ActionSelector";
import { Code, Text } from "@radix-ui/themes";
import { type BasePermissionProps, toSelectorOptions } from "./types";

export function DeletePermission({
  toolCall,
  options,
  onSelect,
  onCancel,
}: BasePermissionProps) {
  const filePath = toolCall.locations?.[0]?.path ?? "";

  return (
    <ActionSelector
      title={toolCall.title ?? "Delete file"}
      pendingAction={
        <>
          <Code title={filePath} className="truncate text-[13px]">
            {compactHomePath(filePath)}
          </Code>
          <Text color="red" mt="1" as="p" className="text-[13px]">
            This action cannot be undone.
          </Text>
        </>
      }
      question="Do you want to delete this file?"
      options={toSelectorOptions(options)}
      onSelect={onSelect}
      onCancel={onCancel}
    />
  );
}
