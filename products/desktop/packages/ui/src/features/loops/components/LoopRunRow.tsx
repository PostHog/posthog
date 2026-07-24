import {
  Check,
  CircleNotch,
  Clock,
  GitBranch,
  type Icon,
  Lightning,
  Play,
  Timer,
  Warning,
  X,
} from "@phosphor-icons/react";
import type { LoopSchemas } from "@posthog/api-client/loops";
import { cn } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { StopCloudRunDialog } from "@posthog/ui/features/sessions/components/StopCloudRunDialog";
import { Badge } from "@posthog/ui/primitives/Badge";
import { Button } from "@posthog/ui/primitives/Button";
import { toast } from "@posthog/ui/primitives/toast";
import { navigateToTaskDetail } from "@posthog/ui/router/navigationBridge";
import { track } from "@posthog/ui/shell/analytics";
import { Flex, Text } from "@radix-ui/themes";
import { type ReactNode, useState } from "react";

function statusColor(
  status: LoopSchemas.LoopRunStatusEnum,
): "gray" | "green" | "red" | "blue" {
  switch (status) {
    case "completed":
      return "green";
    case "failed":
    case "cancelled":
      return "red";
    case "in_progress":
    case "queued":
      return "blue";
    default:
      return "gray";
  }
}

function statusIcon(status: LoopSchemas.LoopRunStatusEnum): Icon {
  switch (status) {
    case "completed":
      return Check;
    case "failed":
    case "cancelled":
      return X;
    case "in_progress":
      return CircleNotch;
    default:
      return Clock;
  }
}

function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const sec = Math.round((Date.now() - then) / 1000);
  if (sec < 45) return "just now";
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.round(hr / 24);
  if (day < 7) return `${day}d ago`;
  return new Date(iso).toLocaleDateString();
}

function formatDuration(ms: number): string {
  const sec = Math.max(0, Math.round(ms / 1000));
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  const rem = sec % 60;
  if (min < 60) return rem ? `${min}m ${rem}s` : `${min}m`;
  const hr = Math.floor(min / 60);
  const remMin = min % 60;
  return remMin ? `${hr}h ${remMin}m` : `${hr}h`;
}

function runDuration(run: LoopSchemas.LoopRun): string {
  if (run.status === "queued" || run.status === "not_started") return "";
  const start = new Date(run.created_at).getTime();
  if (Number.isNaN(start)) return "";
  const end = run.completed_at
    ? new Date(run.completed_at).getTime()
    : Date.now();
  if (Number.isNaN(end)) return "";
  return formatDuration(end - start);
}

function MetaItem({
  icon: IconComponent,
  mono = false,
  children,
}: {
  icon: Icon;
  mono?: boolean;
  children: ReactNode;
}) {
  return (
    <Flex align="center" gap="1" className="min-w-0">
      <IconComponent size={12} weight="bold" className="shrink-0 text-gray-9" />
      <Text
        className={cn(
          "truncate text-[11.5px] text-gray-10",
          mono && "[font-family:var(--font-mono)]",
        )}
      >
        {children}
      </Text>
    </Flex>
  );
}

function isStoppable(run: LoopSchemas.LoopRun): boolean {
  return (
    run.environment === "cloud" &&
    (run.status === "queued" || run.status === "in_progress")
  );
}

export function LoopRunRow({
  loopId,
  run,
  onStopped,
}: {
  loopId: string;
  run: LoopSchemas.LoopRun;
  onStopped?: () => void;
}) {
  const StatusIcon = statusIcon(run.status);
  const duration = runDuration(run);
  const triggered = Boolean(run.loop_trigger_id);
  const stoppable = isStoppable(run);
  const [stopOpen, setStopOpen] = useState(false);

  return (
    <Flex
      align="center"
      justify="between"
      gap="3"
      className="rounded-(--radius-2) border border-border bg-(--color-panel-solid) px-3 py-2.5"
    >
      <Flex direction="column" className="min-w-0 gap-1.5">
        <Flex align="center" gap="2" wrap="wrap">
          <Badge color={statusColor(run.status)}>
            <StatusIcon
              size={10}
              weight="bold"
              className={cn(run.status === "in_progress" && "animate-spin")}
            />
            {run.status.replaceAll("_", " ")}
          </Badge>
          <Text
            className="text-[12px] text-gray-11"
            title={new Date(run.created_at).toLocaleString()}
          >
            {formatRelative(run.created_at)}
          </Text>
        </Flex>
        <Flex align="center" gap="3" wrap="wrap" className="min-w-0">
          {run.branch ? (
            <MetaItem icon={GitBranch} mono>
              {run.branch}
            </MetaItem>
          ) : null}
          {duration ? <MetaItem icon={Timer}>{duration}</MetaItem> : null}
          <MetaItem icon={triggered ? Lightning : Play}>
            {triggered ? "Triggered" : "Manual"}
          </MetaItem>
        </Flex>
        {run.error_message ? (
          <Flex align="center" gap="1" className="min-w-0">
            <Warning
              size={12}
              weight="bold"
              className="shrink-0 text-(--red-11)"
            />
            <Text className="truncate text-(--red-11) text-[11.5px]">
              {run.error_message}
            </Text>
          </Flex>
        ) : null}
      </Flex>
      <Flex align="center" gap="2" className="shrink-0">
        {stoppable ? (
          <Button
            variant="soft"
            color="red"
            size="1"
            onClick={() => setStopOpen(true)}
          >
            Stop run
          </Button>
        ) : null}
        <Button
          variant="soft"
          color="gray"
          size="1"
          onClick={() => {
            track(ANALYTICS_EVENTS.LOOP_RUN_VIEWED, {
              loop_id: loopId,
              run_id: run.id,
              task_id: run.task_id,
              status: run.status,
              environment: run.environment,
              is_manual_run: !triggered,
            });
            navigateToTaskDetail(run.task_id);
          }}
        >
          View run
        </Button>
      </Flex>
      {stoppable || stopOpen ? (
        <StopCloudRunDialog
          open={stopOpen}
          taskId={run.task_id}
          runId={run.id}
          title="Stop run"
          buttonLabel="Stop run"
          onOpenChange={setStopOpen}
          onStopped={() => {
            toast.success("Run stopped");
            onStopped?.();
          }}
        />
      ) : null}
    </Flex>
  );
}
