import { cn } from "@posthog/quill";
import {
  formatConventionalCommitTag,
  getConventionalCommitTypeMeta,
} from "@posthog/ui/features/inbox/components/conventionalCommitTypeMeta";
import { InboxBadge } from "@posthog/ui/features/inbox/components/utils/InboxBadge";
import type { ReactNode } from "react";

interface ConventionalCommitScopeTagProps {
  type: string;
  scope: string | null;
  compact?: boolean;
}

export function ConventionalCommitScopeTag({
  type,
  scope,
  compact = false,
}: ConventionalCommitScopeTagProps): ReactNode {
  const meta = getConventionalCommitTypeMeta(type);
  const IconComponent = meta.icon;
  const label = formatConventionalCommitTag(type, scope);

  return (
    // Rendered as an inline prefix inside the title text (not a flex sibling),
    // so it stays on the title's first line and the title wraps beneath it.
    // `align-middle` keeps it centered on that line.
    <InboxBadge
      variant={compact ? "default" : meta.variant}
      className={cn(
        "mr-1.5 select-none gap-1 whitespace-nowrap align-middle font-mono font-normal",
        compact &&
          "h-5 gap-0.5 border border-(--gray-4) bg-(--gray-2) px-1.5 py-0 text-[11px] text-gray-11 leading-none",
      )}
      title={label}
    >
      <IconComponent
        size={compact ? 10 : 12}
        weight="bold"
        className={compact ? meta.softIconClass : undefined}
        aria-hidden
      />
      {label}
    </InboxBadge>
  );
}
