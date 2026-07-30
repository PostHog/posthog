import { Flex, Text } from "@radix-ui/themes";
import { Cpu } from "lucide-react";
import { useMemo } from "react";
import {
  CardSparkline,
  InfoStat,
  ProcessTable,
  ProfilingTip,
  StatusBadge,
  trendOf,
  useMetricsHistory,
} from "./MetricsCommon";

interface CpuPanelProps {
  enabled: boolean;
}

type CpuStatus = "idle" | "normal" | "busy" | "critical";

function statusFor(cpu: number): CpuStatus {
  if (cpu >= 60) return "critical";
  if (cpu >= 30) return "busy";
  if (cpu >= 10) return "normal";
  return "idle";
}

const STATUS_META: Record<
  CpuStatus,
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
  idle: {
    label: "Idle",
    level: "ok",
    valueColor: "text-(--gray-12)",
    lineClass: "text-(--accent-9)",
    barClass: "bg-(--accent-9)",
    hint: "Plenty of headroom.",
  },
  normal: {
    label: "Normal",
    level: "ok",
    valueColor: "text-(--gray-12)",
    lineClass: "text-(--accent-9)",
    barClass: "bg-(--accent-9)",
    hint: "Healthy steady-state load.",
  },
  busy: {
    label: "Busy",
    level: "warn",
    valueColor: "text-(--amber-11)",
    lineClass: "text-(--amber-9)",
    barClass: "bg-(--amber-9)",
    emphasis: "amber",
    hint: "Sustained load. Watch for jank.",
  },
  critical: {
    label: "Critical",
    level: "crit",
    valueColor: "text-(--red-11)",
    lineClass: "text-(--red-9)",
    barClass: "bg-(--red-9)",
    emphasis: "red",
    hint: "Likely freezing UI. Profile now.",
  },
};

export function CpuPanel({ enabled }: CpuPanelProps) {
  const { sample, history } = useMetricsHistory(enabled);

  const cpuHistory = useMemo(
    () => history.map((h) => h.totalCpuPercent),
    [history],
  );
  const cpuPeak = cpuHistory.length ? Math.max(...cpuHistory) : 0;
  const cpuAvg = cpuHistory.length
    ? cpuHistory.reduce((a, b) => a + b, 0) / cpuHistory.length
    : 0;
  const trend = trendOf(cpuHistory);
  const busiest = useMemo(() => {
    if (!sample || sample.processes.length === 0) return null;
    return [...sample.processes].sort((a, b) => b.cpuPercent - a.cpuPercent)[0];
  }, [sample]);

  if (!sample) {
    return (
      <Flex align="center" justify="center" className="h-full">
        <Text size="1" color="gray">
          Waiting for CPU samples...
        </Text>
      </Flex>
    );
  }

  const status = statusFor(sample.totalCpuPercent);
  const meta = STATUS_META[status];
  const trendLabel =
    trend === "up" ? "↑ trending up" : trend === "down" ? "↓ easing" : "→ flat";
  const barWidth = Math.min(100, sample.totalCpuPercent);

  return (
    <Flex direction="column" gap="3" className="h-full overflow-y-auto p-4">
      <div className="shrink-0 overflow-hidden rounded-md border border-(--gray-5) bg-(--gray-1)">
        <Flex
          align="center"
          gap="2"
          className="border-(--gray-5) border-b bg-(--gray-2) px-3 py-1.5"
        >
          <span className="text-(--gray-10)">
            <Cpu size={14} />
          </span>
          <Text size="1" weight="medium" className="text-(--gray-11) uppercase">
            CPU
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
              {sample.totalCpuPercent.toFixed(1)}%
            </Text>
            <Text size="1" className="text-(--gray-10) leading-tight">
              {meta.hint}
            </Text>
          </Flex>
          <Flex direction="column" justify="center" gap="2">
            <CardSparkline
              history={cpuHistory}
              ymax={Math.max(20, cpuPeak)}
              lineClass={meta.lineClass}
              unit="%"
              height={80}
            />
            <div className="h-1 overflow-hidden rounded-full bg-(--gray-4)">
              <div
                className={`h-full rounded-full ${meta.barClass}`}
                style={{ width: `${barWidth}%` }}
              />
            </div>
          </Flex>
        </div>
        <div className="grid grid-cols-4 gap-3 border-(--gray-5) border-t bg-(--gray-2) px-3 py-2">
          <InfoStat label="Peak" value={`${cpuPeak.toFixed(1)}%`} />
          <InfoStat label="Avg" value={`${cpuAvg.toFixed(1)}%`} />
          <InfoStat label="Procs" value={String(sample.processes.length)} />
          <InfoStat
            label="Busiest"
            value={busiest ? `${busiest.cpuPercent.toFixed(1)}%` : "—"}
            hint={
              busiest
                ? `${busiest.type}${busiest.name ? `: ${busiest.name}` : ""}`
                : undefined
            }
            emphasis={
              busiest && busiest.cpuPercent > 25
                ? "red"
                : busiest && busiest.cpuPercent > 5
                  ? "amber"
                  : undefined
            }
          />
        </div>
      </div>

      <ProfilingTip topic="cpu" />

      <ProcessTable processes={sample.processes} sortBy="cpu" />
    </Flex>
  );
}
