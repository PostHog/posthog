import {
  GROUP_PREVIEW_COUNT,
  groupReportSignals,
  type SignalSourceGroup,
  shouldGroupSignals,
} from "@posthog/core/inbox/signalGrouping";
import type { Signal } from "@posthog/shared/types";
import {
  SignalCard,
  signalCardSourceLine,
} from "@posthog/ui/features/inbox/components/detail/SignalCard";
import { getSourceProductMeta } from "@posthog/ui/features/inbox/components/utils/source-product-icons";
import { useState } from "react";

interface SignalsListProps {
  signals: Signal[];
}

/**
 * Evidence list. Small sets render flat; larger sets consolidate by source
 * product — a header with the count, a couple of representative cards, and a
 * "Show all" expander — so 50 exceptions read as one section, not a wall.
 */
export function SignalsList({ signals }: SignalsListProps) {
  if (!shouldGroupSignals(signals)) {
    return (
      <div className="flex flex-col gap-2">
        {signals.map((signal) => (
          <SignalCard key={signal.signal_id} signal={signal} />
        ))}
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-4">
      {groupReportSignals(signals).map((group) => (
        <SignalSourceGroupSection key={group.key} group={group} />
      ))}
    </div>
  );
}

function SignalSourceGroupSection({ group }: { group: SignalSourceGroup }) {
  const [expanded, setExpanded] = useState(false);
  const meta = getSourceProductMeta(group.sourceProduct);
  const Icon = meta?.Icon;
  // The same "Error tracking · New issue" line the cards themselves carry, so
  // the section header and its cards can't disagree on the source's name.
  const label = signalCardSourceLine(group.signals[0]);
  const shown = expanded
    ? group.signals
    : group.signals.slice(0, GROUP_PREVIEW_COUNT);
  const hiddenCount = group.signals.length - shown.length;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-1.5 text-[13px] text-gray-11">
        {Icon && <Icon size={13} className="shrink-0 text-gray-10" />}
        <span className="font-medium">{label}</span>
        <span className="text-gray-10 tabular-nums">
          · {group.signals.length}
        </span>
      </div>
      {shown.map((signal) => (
        <SignalCard key={signal.signal_id} signal={signal} />
      ))}
      {(hiddenCount > 0 || expanded) && (
        <button
          type="button"
          onClick={() => setExpanded((open) => !open)}
          className="self-start text-[13px] text-gray-10 underline decoration-dotted underline-offset-2 transition-colors hover:text-gray-12"
        >
          {expanded ? "Show fewer" : `Show all ${group.signals.length}`}
        </button>
      )}
    </div>
  );
}

/**
 * Placeholder list rendered while the signals query is in flight. We already
 * know the count from `report.signal_count`, so the side column reserves the
 * right amount of space and doesn't jump when the real data lands.
 */
export function SignalsListSkeleton({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <div className="flex flex-col gap-2" aria-hidden>
      {Array.from({ length: count }, (_, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: skeletons are interchangeable placeholders
        <SignalCardSkeleton key={i} />
      ))}
    </div>
  );
}

function SignalCardSkeleton() {
  return (
    <div className="min-w-0 cursor-default select-none overflow-hidden rounded-(--radius-2) border border-(--gray-6) bg-gray-1 p-3">
      <div className="mb-2 flex items-center gap-2">
        <span className="h-3.5 w-3.5 shrink-0 animate-pulse rounded bg-(--gray-3)" />
        <span className="h-3 w-40 animate-pulse rounded bg-(--gray-3)" />
        <span className="flex-1" />
        <span className="h-3 w-16 animate-pulse rounded bg-(--gray-3)" />
      </div>
      <div className="flex flex-col gap-1.5">
        <span className="h-3 w-full animate-pulse rounded bg-(--gray-3)" />
        <span className="h-3 w-[88%] animate-pulse rounded bg-(--gray-3)" />
        <span className="h-3 w-[72%] animate-pulse rounded bg-(--gray-3)" />
      </div>
    </div>
  );
}
