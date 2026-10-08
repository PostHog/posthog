import {
  getPrVisualConfig,
  parsePrNumber,
  summarizePrChecks,
} from "@posthog/core/git-interaction/prStatus";
import { taskStarter } from "@posthog/core/tasks/taskStatusPresentation";
import { Badge, Card, CardContent } from "@posthog/quill";
import { formatRelativeTimeShort } from "@posthog/shared";
import { ActivityPresenceAvatar } from "@posthog/ui/features/canvas/components/ChannelItemPresence";
import type { SpacePullRequest } from "@posthog/ui/features/canvas/components/work/useSpacePullRequests";
import { getPrVisualIcon } from "@posthog/ui/features/git-interaction/prIcon";
import { usePrChecks } from "@posthog/ui/features/pr-review/usePrChecks";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";

function CiDot({ ci }: { ci: { label: string; color: string } }) {
  return (
    <span
      role="img"
      aria-label={ci.label}
      className="size-1.5 shrink-0 rounded-full"
      style={{ backgroundColor: ci.color }}
    />
  );
}

export function PrFeedRow({
  pullRequest,
  listRow,
}: {
  pullRequest: SpacePullRequest;
  listRow: boolean;
}) {
  const { url, task, details, title } = pullRequest;
  const live = !!details && !details.merged && details.state !== "closed";
  const checks = usePrChecks(live ? url : null);
  const ci = summarizePrChecks(checks.data);
  const config = getPrVisualConfig(
    details?.state ?? "open",
    details?.merged ?? false,
    details?.draft ?? false,
  );
  const Icon = getPrVisualIcon(config.icon);
  const prNumber = parsePrNumber(url);
  const settled = details !== undefined;
  const label = title ?? task.title;
  const number = prNumber ? `#${prNumber}` : "PR";
  const starter = taskStarter(task);
  const open = () => openExternalUrl(url);
  const icon = (
    <Icon
      size={listRow ? 13 : 14}
      style={settled ? { color: `var(--${config.color}-9)` } : undefined}
      className={settled ? undefined : "opacity-50"}
      aria-hidden
    />
  );

  if (!listRow) {
    return (
      <Card
        size="sm"
        role="button"
        tabIndex={0}
        className="my-1.5 w-full cursor-pointer rounded-xl bg-(--gray-2) py-0 transition-colors hover:border-(--gray-7) hover:bg-(--gray-3)"
        onClick={open}
        onKeyDown={(event) => {
          if (event.target !== event.currentTarget) return;
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            open();
          }
        }}
      >
        <CardContent className="flex flex-col px-4 pt-3.5 pb-3">
          <div className="flex items-center gap-3">
            <div className="flex min-w-0 flex-1 items-baseline gap-1.5">
              <span className="flex size-3.5 shrink-0 translate-y-0.5 items-center justify-center">
                {icon}
              </span>
              <span className="shrink-0 text-muted-foreground text-xs tabular-nums">
                {number}
              </span>
              <span className="min-w-0 truncate font-semibold text-sm">
                {label}
              </span>
              <span className="shrink-0 text-muted-foreground text-xs tabular-nums">
                · {formatRelativeTimeShort(task.updated_at)}
              </span>
            </div>
            <Badge>{config.label}</Badge>
          </div>
          <p className="mt-1 line-clamp-1 text-(--gray-11) text-[13px]">
            {task.repository ? `${task.repository} · ` : ""}
            {task.title}
          </p>
          <div className="mt-3 flex items-center justify-end gap-2">
            {ci && <CiDot ci={ci} />}
            {starter && (
              <ActivityPresenceAvatar
                user={starter}
                label="on this pull request"
                activityAt={task.updated_at}
              />
            )}
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <button
      type="button"
      onClick={open}
      title={label}
      className="group relative flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-[13px] transition-colors hover:bg-fill-selected"
    >
      <span className="flex size-3.5 shrink-0 items-center justify-center">
        {icon}
      </span>
      <span className="shrink-0 text-muted-foreground text-xs tabular-nums">
        {number}
      </span>
      <span className="min-w-0 flex-1 truncate font-medium">{label}</span>
      {ci && <CiDot ci={ci} />}
      <ActivityPresenceAvatar
        user={starter}
        label="on this pull request"
        activityAt={task.updated_at}
      />
      <span className="w-8 shrink-0 text-right text-muted-foreground text-xs tabular-nums">
        {formatRelativeTimeShort(task.updated_at)}
      </span>
    </button>
  );
}
