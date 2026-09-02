import type { PrCheck } from "@posthog/core/git/router-schemas";
import {
  type PrCiStatus,
  PrRefChip,
} from "@posthog/ui/features/editor/components/PrRefChip";
import { usePrDetails } from "@posthog/ui/features/git-interaction/usePrDetails";
import { usePrChecks } from "@posthog/ui/features/pr-review/usePrChecks";
import { type ReactElement, type ReactNode, useState } from "react";

function summarizeCiStatus(
  checks: PrCheck[] | null | undefined,
): PrCiStatus | null {
  if (!checks || checks.length === 0) return null;
  if (
    checks.some((check) => check.bucket === "fail" || check.bucket === "cancel")
  ) {
    return "failure";
  }
  if (checks.some((check) => check.bucket === "pending")) return "pending";
  return checks.some((check) => check.bucket === "pass") ? "success" : null;
}

/** A pull request chip wired to live lifecycle and CI state. */
export function GithubPrRefChip({
  href,
  children,
}: {
  href: string;
  children: ReactNode;
}): ReactElement {
  const [tooltipOpen, setTooltipOpen] = useState(false);
  const { meta } = usePrDetails(href, { refetchInterval: 30_000 });
  // CI is the expensive half, so it loads only once someone asks to see it.
  const checksQuery = usePrChecks(tooltipOpen ? href : null);

  return (
    <PrRefChip
      href={href}
      onTooltipOpenChange={setTooltipOpen}
      details={{
        state: meta.state,
        merged: meta.merged,
        draft: meta.draft,
        title: meta.title,
        author: meta.author,
        isLoading: meta.isLoading,
        ciStatus: tooltipOpen ? summarizeCiStatus(checksQuery.data) : null,
        isCiLoading: tooltipOpen && checksQuery.isLoading,
      }}
    >
      {children}
    </PrRefChip>
  );
}
