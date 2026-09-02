import { getFilename } from "@posthog/ui/features/sessions/components/session-update/toolCallUtils";
import { ActionSelector } from "@posthog/ui/primitives/ActionSelector";
import { Code } from "@radix-ui/themes";
import {
  type BasePermissionProps,
  findDiffContent,
  toSelectorOptions,
} from "./types";

export function EditPermission({
  toolCall,
  options,
  onSelect,
  onCancel,
}: BasePermissionProps) {
  const diff = findDiffContent(toolCall.content);
  const filePath = diff?.path ?? toolCall.locations?.[0]?.path ?? "";
  const isNewFile = diff && !diff.oldText;

  return (
    <ActionSelector
      title={isNewFile ? "Create new file" : (toolCall.title ?? "Edit file")}
      question={
        isNewFile ? (
          <>
            Do you want to create{" "}
            <Code variant="ghost" className="font-bold">
              {getFilename(filePath)}
            </Code>
            ?
          </>
        ) : (
          "Do you want to apply this edit?"
        )
      }
      options={toSelectorOptions(options)}
      onSelect={onSelect}
      onCancel={onCancel}
    />
  );
}
