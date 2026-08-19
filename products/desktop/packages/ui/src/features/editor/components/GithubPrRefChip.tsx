import type { PrCheck } from "@posthog/core/git/router-schemas";
import {
  type GithubPrRefDetails,
  GithubRefChip,
} from "@posthog/ui/features/editor/components/GithubRefChip";
import { usePrDetails } from "@posthog/ui/features/git-interaction/usePrDetails";
import { usePrChecks } from "@posthog/ui/features/pr-review/usePrChecks";
import { type ReactElement, type ReactNode, useState } from "react";

function summarizeCiStatus(
  checks: PrCheck[] | null | undefined,
): GithubPrRefDetails["ciStatus"] {
  if (!checks || checks.length === 0) return null;
  if (
    checks.some((check) => check.bucket === "fail" || check.bucket === "cancel")
  ) {
    return "failure";
  }
  if (checks.some((check) => check.bucket === "pending")) return "pending";
  return checks.some((check) => check.bucket === "pass") ? "success" : null;
}

export function GithubPrRefChip({
  href,
  children,
}: {
  href: string;
  children: ReactNode;
}): ReactElement {
  const [tooltipOpen, setTooltipOpen] = useState(false);
  const { meta } = usePrDetails(href, { refetchInterval: 30_000 });
  const checksQuery = usePrChecks(tooltipOpen ? href : null);
  const ciStatus = tooltipOpen
    ? checksQuery.isLoading
      ? "loading"
      : summarizeCiStatus(checksQuery.data)
    : null;

  return (
    <GithubRefChip
      href={href}
      kind="pr"
      prDetails={{ ...meta, ciStatus }}
      onTooltipOpenChange={setTooltipOpen}
    >
      {children}
    </GithubRefChip>
  );
}
