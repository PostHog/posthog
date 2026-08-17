import type { Signal } from "@posthog/shared/types";
import { SignalCard } from "@posthog/ui/features/inbox/components/detail/SignalCard";
import { Box, Flex } from "@radix-ui/themes";

interface SignalsListProps {
  signals: Signal[];
}

export function SignalsList({ signals }: SignalsListProps) {
  return (
    <Flex direction="column" gap="2">
      {signals.map((signal) => (
        <SignalCard key={signal.signal_id} signal={signal} />
      ))}
    </Flex>
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
