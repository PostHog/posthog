import type { SignalReportActionability } from "@posthog/shared/domain-types";
import { InboxBadge } from "@posthog/ui/features/inbox/components/utils/InboxBadge";
import { Tooltip } from "@radix-ui/themes";
import type { ReactNode } from "react";

const ACTIONABILITY_STYLE: Record<
  SignalReportActionability,
  { variant: "success" | "warning" | "default"; label: string; tooltip: string }
> = {
  immediately_actionable: {
    variant: "success",
    label: "Actionable",
    tooltip:
      "The report can be solved with code. If there isn't a pull request yet, it fell below your auto-PR priority threshold. You can still start one from this report.",
  },
  requires_human_input: {
    variant: "warning",
    label: "Needs input",
    tooltip:
      "Actionable, but it needs your input first to decide how to resolve it: business context, trade-offs, or a choice between several valid approaches.",
  },
  not_actionable: {
    variant: "default",
    label: "Not actionable",
    tooltip:
      "No useful code change can be derived because the report is too vague, lacks supporting evidence, or describes expected behavior.",
  },
};

interface SignalReportActionabilityBadgeProps {
  actionability: SignalReportActionability | null | undefined;
}

export function SignalReportActionabilityBadge({
  actionability,
}: SignalReportActionabilityBadgeProps): ReactNode {
  if (actionability == null) {
    return null;
  }

  const style = ACTIONABILITY_STYLE[actionability];
  if (!style) {
    return null;
  }

  return (
    <Tooltip content={style.tooltip}>
      <InboxBadge variant={style.variant} className="cursor-help">
        {style.label}
      </InboxBadge>
    </Tooltip>
  );
}
