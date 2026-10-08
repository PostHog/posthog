import { WarningCircleIcon } from "@phosphor-icons/react";
import { Text } from "@posthog/quill";

export function BrokenBlockNotice({
  section,
  error,
}: {
  section: string;
  error: string;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-md border border-border border-dashed p-4">
      <Text size="sm" weight="medium" className="flex items-center gap-1.5">
        <WarningCircleIcon size={14} className="text-warning-foreground" />
        The {section} block in CONTEXT.md could not be read.
      </Text>
      <Text size="xs" variant="muted">
        Nothing is lost. The block is kept as it is until it is fixed in the
        wiki, and everything else on this page still works.
      </Text>
      <pre className="overflow-x-auto whitespace-pre-wrap text-muted-foreground text-xxs">
        {error}
      </pre>
    </div>
  );
}
