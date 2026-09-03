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
}

export function ConventionalCommitScopeTag({
  type,
  scope,
}: ConventionalCommitScopeTagProps): ReactNode {
  const meta = getConventionalCommitTypeMeta(type);
  const IconComponent = meta.icon;
  const label = formatConventionalCommitTag(type, scope);

  // `align-middle` keeps the tag centered on the title's first line when it
  // renders as an inline prefix inside the title text; `font-normal` stops it
  // inheriting the title's weight.
  return (
    <InboxBadge
      variant="default"
      className={cn(
        "shrink-0 border border-(--gray-4) bg-(--gray-2) align-middle font-mono font-normal text-gray-11 leading-none",
        "mr-1.5 h-5 gap-0.5 px-1.5 py-0 text-[11px]",
      )}
      title={label}
    >
      <IconComponent
        size={10}
        weight="bold"
        className={meta.softIconClass}
        aria-hidden
      />
      {label}
    </InboxBadge>
  );
}
