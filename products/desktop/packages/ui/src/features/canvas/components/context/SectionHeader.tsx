import { Text } from "@posthog/quill";
import type { ReactNode } from "react";

export function SectionHeader({
  label,
  action,
}: {
  label: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex h-6 items-center justify-between gap-2">
      <Text size="xs" weight="medium" variant="muted">
        {label}
      </Text>
      {action}
    </div>
  );
}
