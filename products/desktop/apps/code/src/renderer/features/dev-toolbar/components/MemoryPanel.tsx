import { Flex, Text } from "@radix-ui/themes";
import { MemoryStick } from "lucide-react";
import { useMemo } from "react";
import {
  CardSparkline,
  formatMemory,
  InfoStat,
  ProcessTable,
  ProfilingTip,
  StatusBadge,
  trendOf,
  useMetricsHistory,
} from "./MetricsCommon";

interface MemoryPanelProps {
  enabled: boolean;
}

type MemStatus = "healthy" | "warm" | "tight" | "pressure";

function statusFor(heapPct: number): MemStatus {
  if (heapPct >= 90) return "pressure";
  if (heapPct >= 75) return "tight";
  if (heapPct >= 50) return "warm";
  return "healthy";
}

const STATUS_META: Record<
  MemStatus,
  {
    label: string;
    level: "ok" | "warn" | "crit";
    valueColor: string;
    lineClass: string;
    barClass: string;
    emphasis?: "red" | "amber";
    hint: string;
  }
> = {
  healthy: {
    label: "Healthy",
    level: "ok",
    valueColor: "text-(--gray-12)",
    lineClass: "text-(--accent-9)",
    barClass: "bg-(--accent-9)",
    hint: "Heap has room to grow.",
  },
  warm: {
    label: "Warm",
    level: "ok",
    valueColor: "text-(--gray-12)",
    lineClass: "text-(--accent-9)",
    barClass: "bg-(--accent-9)",
    hint: "Half the heap in use. Normal for active sessions.",
  },
  tight: {
    label: "Tight",
    level: "warn",
    valueColor: "text-(--amber-11)",
    lineClass: "text-(--amber-9)",
    barClass: "bg-(--amber-9)",
    emphasis: "amber",
    hint: "Heap getting full. GC pressure rising.",
  },
  pressure: {
    label: "Pressure",
    level: "crit",
    valueColor: "text-(--red-11)",
    lineClass: "text-(--red-9)",
    barClass: "bg-(--red-9)",
    emphasis: "red",
    hint: "Near heap limit. Snapshot now.",
  },
};

export function MemoryPanel({ enabled }: MemoryPanelProps) {
  const { sample, history } = useMetricsHistory(enabled);

  const memHistory = useMemo(
    () => history.map((h) => h.totalMemoryMb),
    [history],
  );
  const heapHistory = useMemo(
    () => history.map((h) => h.heapUsedMb),
    [history],
  );
  const memPeak = memHistory.length ? Math.max(...memHistory) : 0;
  const memAvg = memHistory.length
    ? memHistory.reduce((a, b) => a + b, 0) / memHistory.length
    : 0;
  const heapTrend = trendOf(heapHistory);
  const biggest = useMemo(() => {
    if (!sample || sample.processes.length === 0) return null;
    return [...sample.processes].sort((a, b) => b.memoryMb - a.memoryMb)[0];
  }, [sample]);

  if (!sample) {
    return (
      <Flex align="center" justify="center" className="h-full">
        <Text size="1" color="gray">
          Waiting for memory samples...
        </Text>
      </Flex>
    );
  }

  const heapPct =
    sample.heapTotalMb > 0 ? (sample.heapUsedMb / sample.heapTotalMb) * 100 : 0;
  const headroomMb = Math.max(0, sample.heapTotalMb - sample.heapUsedMb);
  const status = statusFor(heapPct);
  const meta = STATUS_META[status];
  const trendLabel =
    heapTrend === "up"
      ? "↑ heap growing"
      : heapTrend === "down"
        ? "↓ heap shrinking"
        : "→ heap stable";

  return (
    <Flex direction="column" gap="3" className="h-full overflow-y-auto p-4">
      <div className="shrink-0 overflow-hidden rounded-md border border-(--gray-5) bg-(--gray-1)">
        <Flex
          align="center"
          gap="2"
          className="border-(--gray-5) border-b bg-(--gray-2) px-3 py-1.5"
        >
          <span className="text-(--gray-10)">
            <MemoryStick size={14} />
          </span>
          <Text size="1" weight="medium" className="text-(--gray-11) uppercase">
            Memory
          </Text>
          <StatusBadge level={meta.level}>{meta.label}</StatusBadge>
          <Text size="1" className="ml-auto font-mono text-(--gray-10)">
            {trendLabel}
          </Text>
        </Flex>
        <div className="grid grid-cols-[160px_1fr] gap-4 p-3">
          <Flex direction="column" justify="center" gap="1">
            <Text
              size="8"
              weight="bold"
              className={`font-mono leading-none ${meta.valueColor}`}
            >
              {formatMemory(sample.totalMemoryMb)}
            </Text>
            <Text size="1" className="text-(--gray-10) leading-tight">
              {meta.hint}
            </Text>
          </Flex>
          <Flex direction="column" justify="center" gap="2">
            <CardSparkline
              history={memHistory}
              secondaryHistory={heapHistory}
              ymax={Math.max(memPeak, sample.heapTotalMb)}
              lineClass={meta.lineClass}
              unit="MB"
              height={80}
            />
            <Flex align="center" gap="2">
              <div className="h-1 flex-1 overflow-hidden rounded-full bg-(--gray-4)">
                <div
                  className={`h-full rounded-full ${meta.barClass}`}
                  style={{ width: `${Math.min(100, heapPct)}%` }}
                />
              </div>
              <Text size="1" className="font-mono text-(--gray-10)">
                {heapPct.toFixed(0)}% heap
              </Text>
            </Flex>
          </Flex>
        </div>
        <div className="grid grid-cols-4 gap-3 border-(--gray-5) border-t bg-(--gray-2) px-3 py-2">
          <InfoStat label="Peak" value={formatMemory(memPeak)} />
          <InfoStat label="Avg" value={formatMemory(memAvg)} />
          <InfoStat
            label="Headroom"
            value={formatMemory(headroomMb)}
            emphasis={meta.emphasis}
          />
          <InfoStat
            label="Heaviest"
            value={biggest ? formatMemory(biggest.memoryMb) : "—"}
            hint={
              biggest
                ? `${biggest.type}${biggest.name ? `: ${biggest.name}` : ""}`
                : undefined
            }
          />
        </div>
      </div>

      <ProfilingTip topic="memory" />

      <ProcessTable processes={sample.processes} sortBy="memory" />
    </Flex>
  );
}
