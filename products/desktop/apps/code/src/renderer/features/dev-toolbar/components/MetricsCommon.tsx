import { Flex, Text } from "@radix-ui/themes";
import { useTRPC } from "@renderer/trpc/client";
import { useSubscription } from "@trpc/tanstack-react-query";
import { Lightbulb } from "lucide-react";
import { useState } from "react";
import type {
  MetricsSample,
  ProcessSample,
} from "../../../../main/services/dev-metrics/schemas";

interface TipItem {
  label: string;
  detail: string;
}

const CPU_TIPS: TipItem[] = [
  {
    label: "Renderer profile",
    detail: "Cmd+Opt+I → Performance → Record while reproducing",
  },
  {
    label: "Main process",
    detail: "ELECTRON_RUN_AS_NODE=1 electron --inspect, then chrome://inspect",
  },
  {
    label: "System sample",
    detail: "Activity Monitor → Sample Process, or sample <pid> 10",
  },
];

const MEMORY_TIPS: TipItem[] = [
  {
    label: "Heap snapshot",
    detail: "Cmd+Opt+I → Memory → Heap snapshot, diff two to find growth",
  },
  {
    label: "Detached DOM",
    detail: 'In Heap, filter by "Detached" to find leaked nodes',
  },
  {
    label: "System view",
    detail: "Activity Monitor → Memory, compare Memory vs Compressed",
  },
];

export const HISTORY_LENGTH = 60;

export function useMetricsHistory(enabled: boolean) {
  const trpcReact = useTRPC();
  const [sample, setSample] = useState<MetricsSample | null>(null);
  const [history, setHistory] = useState<MetricsSample[]>([]);

  useSubscription(
    trpcReact.dev.onMetrics.subscriptionOptions(undefined, {
      enabled,
      onData: (data) => {
        setSample(data);
        setHistory((prev) => {
          const next = [...prev, data];
          return next.length > HISTORY_LENGTH
            ? next.slice(next.length - HISTORY_LENGTH)
            : next;
        });
      },
    }),
  );

  return { sample, history };
}

export function formatMemory(mb: number): string {
  if (mb >= 1024) return `${(mb / 1024).toFixed(2)}GB`;
  return `${mb.toFixed(0)}MB`;
}

export function trendOf(values: number[]): "up" | "down" | "flat" {
  if (values.length < 8) return "flat";
  const half = Math.floor(values.length / 2);
  const earlier = values.slice(0, half);
  const later = values.slice(half);
  const avg = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length;
  const diff = avg(later) - avg(earlier);
  const base = Math.max(1, avg(earlier));
  const pct = diff / base;
  if (pct > 0.15) return "up";
  if (pct < -0.15) return "down";
  return "flat";
}

interface StatusBadgeProps {
  level: "ok" | "warn" | "crit";
  children: React.ReactNode;
}

export function StatusBadge({ level, children }: StatusBadgeProps) {
  const styles =
    level === "crit"
      ? "bg-(--red-3) text-(--red-11)"
      : level === "warn"
        ? "bg-(--amber-3) text-(--amber-11)"
        : "bg-(--green-3) text-(--green-11)";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium text-[10px] uppercase tracking-wide ${styles}`}
    >
      {children}
    </span>
  );
}

interface InfoStatProps {
  label: string;
  value: string;
  hint?: string;
  emphasis?: "red" | "amber";
}

export function InfoStat({ label, value, hint, emphasis }: InfoStatProps) {
  const valueColor =
    emphasis === "red"
      ? "text-(--red-11)"
      : emphasis === "amber"
        ? "text-(--amber-11)"
        : "text-(--gray-12)";
  return (
    <Flex direction="column" gap="0">
      <Text size="1" className="text-(--gray-9) uppercase tracking-wide">
        {label}
      </Text>
      <Text size="2" className={`font-mono ${valueColor}`}>
        {value}
      </Text>
      {hint && (
        <Text size="1" className="text-(--gray-9)">
          {hint}
        </Text>
      )}
    </Flex>
  );
}

interface CardSparklineProps {
  history: number[];
  secondaryHistory?: number[];
  ymax: number;
  lineClass: string;
  unit: string;
  height?: number;
}

export function CardSparkline({
  history,
  secondaryHistory,
  ymax,
  lineClass,
  unit,
  height = 64,
}: CardSparklineProps) {
  const width = 320;
  const max = Math.max(1, ymax);
  const step = history.length > 1 ? width / (history.length - 1) : width;

  const linePoints = history
    .map((v, i) => `${i * step},${height - (v / max) * (height - 4) - 2}`)
    .join(" ");
  const areaPoints = `0,${height} ${linePoints} ${(history.length - 1) * step},${height}`;
  const secondaryPoints = secondaryHistory
    ? secondaryHistory
        .map((v, i) => `${i * step},${height - (v / max) * (height - 4) - 2}`)
        .join(" ")
    : null;

  return (
    <svg
      width="100%"
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={`${unit} history sparkline`}
      className="overflow-visible"
    >
      <title>{`${unit} history`}</title>
      <polygon
        points={areaPoints}
        className={`${lineClass} fill-current`}
        opacity="0.12"
      />
      <polyline
        points={linePoints}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        className={lineClass}
      />
      {secondaryPoints && (
        <polyline
          points={secondaryPoints}
          fill="none"
          stroke="currentColor"
          strokeWidth="1"
          strokeDasharray="2 2"
          className="text-(--gray-9)"
        />
      )}
    </svg>
  );
}

interface ProcessTableProps {
  processes: ProcessSample[];
  sortBy: "cpu" | "memory";
}

export function ProcessTable({ processes, sortBy }: ProcessTableProps) {
  const ranked = [...processes].sort((a, b) =>
    sortBy === "cpu" ? b.cpuPercent - a.cpuPercent : b.memoryMb - a.memoryMb,
  );
  return (
    <Flex direction="column" gap="1">
      <Text size="1" weight="medium" color="gray" className="px-1">
        Processes
      </Text>
      <div className="overflow-hidden rounded-md border border-(--gray-5) bg-(--gray-1)">
        <div className="grid grid-cols-[1fr_70px_90px_70px] gap-x-3 border-(--gray-5) border-b bg-(--gray-2) px-3 py-1.5 font-mono text-(--gray-10) text-[10px] uppercase tracking-wide">
          <span>Process</span>
          <span>PID</span>
          <span>Memory</span>
          <span className="text-right">CPU</span>
        </div>
        <div className="divide-y divide-(--gray-4)">
          {ranked.map((p) => (
            <ProcessRow key={`${p.pid}-${p.type}`} {...p} />
          ))}
        </div>
      </div>
    </Flex>
  );
}

function ProcessRow({ pid, type, name, cpuPercent, memoryMb }: ProcessSample) {
  return (
    <div className="grid grid-cols-[1fr_70px_90px_70px] items-center gap-x-3 px-3 py-1 font-mono text-[11px]">
      <Text size="1" className="truncate text-(--gray-12)">
        {name ? `${type}: ${name}` : type}
      </Text>
      <Text size="1" color="gray" className="font-mono">
        {pid}
      </Text>
      <Text size="1" className="font-mono text-(--gray-11)">
        {memoryMb.toFixed(0)} MB
      </Text>
      <Text
        size="1"
        className="text-right font-mono"
        color={cpuPercent > 25 ? "red" : cpuPercent > 5 ? "amber" : undefined}
      >
        {cpuPercent.toFixed(1)}%
      </Text>
    </div>
  );
}

interface ProfilingTipProps {
  topic: "cpu" | "memory";
}

export function ProfilingTip({ topic }: ProfilingTipProps) {
  const tips = topic === "cpu" ? CPU_TIPS : MEMORY_TIPS;
  const heading =
    topic === "cpu" ? "Dig into CPU hotspots" : "Dig into memory pressure";

  return (
    <div className="shrink-0 rounded-md border border-(--amber-6) bg-(--amber-2) p-3">
      <Flex align="center" gap="2" className="mb-2">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-(--amber-4) text-(--amber-11)">
          <Lightbulb size={13} />
        </span>
        <Text size="1" weight="medium" className="text-(--amber-12) uppercase">
          {heading}
        </Text>
      </Flex>
      <div className="grid gap-1.5 sm:grid-cols-3">
        {tips.map((tip) => (
          <div
            key={tip.label}
            className="rounded bg-(--amber-1) px-2 py-1.5 text-[11px] leading-snug"
          >
            <div className="font-medium text-(--amber-12)">{tip.label}</div>
            <div className="text-(--gray-11)">{tip.detail}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
