import { ArrowRightIcon, GlobeIcon } from "@phosphor-icons/react";
import type { LoopSchemas } from "@posthog/api-client/loops";
import {
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@posthog/quill";
import { channelGlyph } from "@posthog/ui/features/canvas/components/channelGlyph";
import { Badge } from "@posthog/ui/primitives/Badge";
import { LoopIcon } from "@posthog/ui/primitives/LoopIcon";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { Link } from "@tanstack/react-router";
import { useUpdateLoop } from "../hooks/useLoopMutations";
import {
  loopPausedDescription,
  loopStatusColor,
  loopStatusLabel,
  summarizeTrigger,
} from "../loopDisplay";
import {
  type LoopScope,
  type LoopSpace,
  resolveLoopScope,
} from "../loopScopes";

const NEXT_RUN_SEPARATOR = " · Next run ";

function triggerLines(loop: LoopSchemas.Loop): {
  primary: string;
  secondary: string | null;
} {
  const [first, ...rest] = loop.triggers;
  if (!first) return { primary: "No trigger", secondary: null };
  const [cadence, nextRun] = summarizeTrigger(first).split(NEXT_RUN_SEPARATOR);
  const more = rest.length > 0 ? `+${rest.length} more` : null;
  return {
    primary: cadence ?? "",
    secondary: nextRun ? `next ${nextRun}` : more,
  };
}

function lastRunLabel(loop: LoopSchemas.Loop): string | null {
  return loop.consecutive_failures > 0
    ? `${loop.consecutive_failures} failed in a row`
    : loop.last_run_status;
}

export function LoopsTable({
  loops,
  spaces,
  emptyMessage,
  showSpace = true,
}: {
  loops: LoopSchemas.Loop[];
  spaces: LoopSpace[];
  emptyMessage: string;
  showSpace?: boolean;
}) {
  return (
    <Table
      fullWidth
      tableClassName="table-fixed"
      className="@container rounded-(--radius-md) border border-border bg-(--color-panel-solid)"
    >
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead
            className={
              showSpace
                ? "@3xl:w-[40%] @xl:w-[44%] w-[58%]"
                : "@3xl:w-[58%] @xl:w-[68%] w-[92%]"
            }
          >
            Loop
          </TableHead>
          {showSpace ? (
            <TableHead className="@3xl:w-[18%] @xl:w-[24%] w-[34%]">
              Space
            </TableHead>
          ) : null}
          <TableHead className="@3xl:table-cell hidden @3xl:w-[20%]">
            Trigger
          </TableHead>
          <TableHead className="@xl:table-cell hidden @3xl:w-[16%] @xl:w-[24%]">
            Last run
          </TableHead>
          <TableHead className="@3xl:w-[6%] w-[8%]" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {loops.length === 0 ? (
          <TableRow className="hover:bg-transparent">
            <TableCell
              colSpan={showSpace ? 5 : 4}
              className="py-10 text-center text-[12.5px] text-gray-10"
            >
              {emptyMessage}
            </TableCell>
          </TableRow>
        ) : (
          loops.map((loop) => (
            <LoopTableRow
              key={loop.id}
              loop={loop}
              scope={resolveLoopScope(loop, spaces)}
              showSpace={showSpace}
            />
          ))
        )}
      </TableBody>
    </Table>
  );
}

function LoopTableRow({
  loop,
  scope,
  showSpace,
}: {
  loop: LoopSchemas.Loop;
  scope: LoopScope;
  showSpace: boolean;
}) {
  const description = loop.description.trim();
  const trigger = triggerLines(loop);
  const runLabel = lastRunLabel(loop);
  const pausedDescription = loopPausedDescription(loop);
  const lastRunFailed =
    loop.consecutive_failures > 0 || loop.last_run_status === "failed";
  const statusBadge = (
    <span className="inline-flex shrink-0">
      <Badge color={loopStatusColor(loop)}>{loopStatusLabel(loop)}</Badge>
    </span>
  );

  return (
    <TableRow className={loop.enabled ? undefined : "opacity-70"}>
      <TableCell className="py-2">
        <div className="flex min-w-0 items-center gap-2.5">
          <LoopIcon size={16} className="shrink-0 text-gray-11" />
          <div className="flex min-w-0 flex-col gap-0.5">
            <div className="flex min-w-0 items-center gap-2">
              {scope.kind === "space" && scope.available ? (
                <Link
                  to="/spaces/$channelId/loops/$loopId"
                  params={{ channelId: scope.channelId, loopId: loop.id }}
                  className="truncate font-medium text-[13px] text-gray-12 no-underline hover:underline"
                >
                  {loop.name}
                </Link>
              ) : (
                <Link
                  to="/loops/$loopId"
                  params={{ loopId: loop.id }}
                  className="truncate font-medium text-[13px] text-gray-12 no-underline hover:underline"
                >
                  {loop.name}
                </Link>
              )}
              {pausedDescription ? (
                <Tooltip content={pausedDescription}>{statusBadge}</Tooltip>
              ) : (
                statusBadge
              )}
              {loop.visibility === "personal" ? (
                <Badge color="gray" className="shrink-0">
                  personal
                </Badge>
              ) : null}
            </div>
            {description ? (
              <span className="truncate text-[12px] text-gray-10">
                {description}
              </span>
            ) : null}
          </div>
        </div>
      </TableCell>

      {showSpace ? (
        <TableCell>
          <LoopScopeCell scope={scope} />
        </TableCell>
      ) : null}

      <TableCell className="@3xl:table-cell hidden">
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="truncate text-[12.5px] text-gray-12">
            {trigger.primary}
          </span>
          {trigger.secondary ? (
            <span className="truncate text-[11px] text-gray-10">
              {trigger.secondary}
            </span>
          ) : null}
        </div>
      </TableCell>

      <TableCell className="@xl:table-cell hidden">
        {loop.last_run_at ? (
          <div className="flex min-w-0 flex-col gap-0.5">
            <RelativeTimestamp
              timestamp={loop.last_run_at}
              className="text-[12.5px] text-gray-12"
            />
            {runLabel ? (
              <span
                className={`truncate text-[11px] ${lastRunFailed ? "text-(--red-11)" : "text-gray-10"}`}
              >
                {runLabel}
              </span>
            ) : null}
          </div>
        ) : (
          <span className="text-[12px] text-gray-9">Never ran</span>
        )}
      </TableCell>

      <TableCell>
        <LoopEnabledSwitch loop={loop} />
      </TableCell>
    </TableRow>
  );
}

function LoopScopeCell({ scope }: { scope: LoopScope }) {
  if (scope.kind === "global") {
    return (
      <span className="flex min-w-0 items-center gap-1.5 text-[12.5px] text-gray-11">
        <GlobeIcon size={14} className="shrink-0" />
        <span className="truncate">Global</span>
      </span>
    );
  }
  const glyph = channelGlyph(scope.label, {
    size: 13,
    personal: scope.channelType === "personal",
    private: scope.channelType === "private",
  });
  if (!scope.available) {
    return (
      <span className="flex min-w-0 items-center gap-1.5 text-[12.5px] text-gray-10">
        <span className="shrink-0">{glyph}</span>
        <span className="truncate">{scope.label}</span>
      </span>
    );
  }
  return (
    <Link
      to="/spaces/$channelId/loops"
      params={{ channelId: scope.channelId }}
      className="group flex min-w-0 items-center gap-1.5 text-[12.5px] text-gray-12 no-underline hover:underline"
    >
      <span className="shrink-0 text-gray-11">{glyph}</span>
      <span className="truncate">{scope.label}</span>
      <ArrowRightIcon
        size={11}
        className="shrink-0 text-gray-8 opacity-0 transition-opacity group-hover:opacity-100"
      />
    </Link>
  );
}

function LoopEnabledSwitch({ loop }: { loop: LoopSchemas.Loop }) {
  const update = useUpdateLoop(loop.id);
  const tooltip = loop.enabled
    ? "Pause this loop"
    : loop.disabled_reason
      ? "Resume this loop"
      : "Turn this loop on";
  return (
    <Tooltip content={tooltip}>
      <span className="inline-flex">
        <Switch
          size="sm"
          checked={loop.enabled}
          disabled={update.isPending}
          onCheckedChange={(checked) => update.mutate({ enabled: checked })}
          aria-label={`${loop.name} enabled`}
        />
      </span>
    </Tooltip>
  );
}
