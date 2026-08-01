import { CaretDownIcon, CaretRightIcon } from "@phosphor-icons/react";
import type { Signal } from "@posthog/shared/types";
import { SignalCard } from "@posthog/ui/features/inbox/components/detail/SignalCard";
import {
  groupSignalsByType,
  type SignalGroup,
  shouldGroupSignals,
} from "@posthog/ui/features/inbox/components/signalGrouping";
import { getSourceProductMeta } from "@posthog/ui/features/inbox/components/utils/source-product-icons";
import { Badge, Box, Flex, Text } from "@radix-ui/themes";
import { useMemo, useState } from "react";

interface SignalsListProps {
  signals: Signal[];
}

export function SignalsList({ signals }: SignalsListProps) {
  const groups = useMemo(() => groupSignalsByType(signals), [signals]);

  if (!shouldGroupSignals(groups, signals.length)) {
    return (
      <Flex direction="column" gap="2">
        {signals.map((signal) => (
          <SignalCard key={signal.signal_id} signal={signal} />
        ))}
      </Flex>
    );
  }

  return (
    <Flex direction="column" gap="2">
      {groups.map((group) => (
        <SignalGroupSection key={group.key} group={group} />
      ))}
    </Flex>
  );
}

function SignalGroupSection({ group }: { group: SignalGroup }) {
  const [expanded, setExpanded] = useState(false);
  const meta = getSourceProductMeta(group.sourceProduct);

  return (
    <Box className="min-w-0 overflow-hidden rounded-(--radius-2) border border-(--gray-6) bg-gray-1">
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full cursor-default items-center gap-2 p-3 text-left hover:bg-gray-2"
      >
        {expanded ? (
          <CaretDownIcon size={12} className="shrink-0 text-gray-10" />
        ) : (
          <CaretRightIcon size={12} className="shrink-0 text-gray-10" />
        )}
        <span
          className="shrink-0"
          style={{ color: meta?.color ?? "var(--gray-9)" }}
        >
          {meta ? (
            <meta.Icon size={14} />
          ) : (
            <span className="inline-block h-2.5 w-2.5 rounded-full bg-(--gray-9)" />
          )}
        </span>
        <Text className="font-medium text-[13px] text-gray-11">
          {group.label}
        </Text>
        <span className="flex-1" />
        <Badge variant="soft" color="gray" size="1" className="text-[11px]">
          {group.signals.length}
        </Badge>
      </button>
      {expanded && (
        <Flex direction="column" gap="2" className="px-3 pb-3">
          {group.signals.map((signal) => (
            <SignalCard key={signal.signal_id} signal={signal} />
          ))}
        </Flex>
      )}
    </Box>
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
    <Flex direction="column" gap="2" aria-hidden>
      {Array.from({ length: count }, (_, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: skeletons are interchangeable placeholders
        <SignalCardSkeleton key={i} />
      ))}
    </Flex>
  );
}

function SignalCardSkeleton() {
  return (
    <Box className="min-w-0 cursor-default select-none overflow-hidden rounded-(--radius-2) border border-(--gray-6) bg-gray-1 p-3">
      <Flex align="center" gap="2" className="mb-2">
        <span className="h-3.5 w-3.5 shrink-0 animate-pulse rounded bg-(--gray-3)" />
        <span className="h-3 w-40 animate-pulse rounded bg-(--gray-3)" />
        <span className="flex-1" />
        <span className="h-3 w-16 animate-pulse rounded bg-(--gray-3)" />
      </Flex>
      <Flex direction="column" gap="1.5">
        <span className="h-3 w-full animate-pulse rounded bg-(--gray-3)" />
        <span className="h-3 w-[88%] animate-pulse rounded bg-(--gray-3)" />
        <span className="h-3 w-[72%] animate-pulse rounded bg-(--gray-3)" />
      </Flex>
    </Box>
  );
}
