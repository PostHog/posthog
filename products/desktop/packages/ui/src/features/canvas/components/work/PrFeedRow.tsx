import {
  getPrVisualConfig,
  parsePrNumber,
} from "@posthog/core/git-interaction/prStatus";
import { Badge, Card, CardContent, cn } from "@posthog/quill";
import { formatRelativeTimeShort } from "@posthog/shared";
import type { UserBasic } from "@posthog/shared/domain-types";
import { ActivityPresenceAvatar } from "@posthog/ui/features/canvas/components/ChannelItemPresence";
import type { SpacePullRequest } from "@posthog/ui/features/canvas/components/work/useSpacePullRequests";
import { getPrVisualIcon } from "@posthog/ui/features/git-interaction/prIcon";
import type { PrStateDetails } from "@posthog/ui/features/git-interaction/usePrDetails";
import { usePrChecks } from "@posthog/ui/features/pr-review/usePrChecks";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";

const CI_DOT_CLASS = {
  pass: "bg-(--green-9)",
  fail: "bg-(--red-9)",
  pending: "bg-(--amber-9)",
} as const;

const CI_LABEL = {
  pass: "CI passing",
  fail: "CI failing",
  pending: "CI running",
} as const;

function ciTone(
  checks: { bucket: string }[] | null | undefined,
): keyof typeof CI_DOT_CLASS | null {
  if (!checks || checks.length === 0) return null;
  if (checks.some((c) => c.bucket === "fail" || c.bucket === "cancel")) {
    return "fail";
  }
  if (checks.some((c) => c.bucket === "pending")) return "pending";
  return "pass";
}

function isLive(details: PrStateDetails | undefined): boolean {
  return !!details && !details.merged && details.state !== "closed";
}

function CiDot({ tone }: { tone: keyof typeof CI_DOT_CLASS }) {
  return (
    <span
      role="img"
      aria-label={CI_LABEL[tone]}
      className={cn("size-1.5 shrink-0 rounded-full", CI_DOT_CLASS[tone])}
    />
  );
}

export function PrFeedRow({
  pullRequest,
  listRow,
  wide,
}: {
  pullRequest: SpacePullRequest;
  listRow: boolean;
  wide: boolean;
}) {
  const { url, task, details, title } = pullRequest;
  const live = isLive(details);
  const checks = usePrChecks(live ? url : null);
  const tone = ciTone(checks.data);
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
  const starter: UserBasic | null =
    task.origin_product === "user_created" ? (task.created_by ?? null) : null;
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
        className={cn(
          "mx-auto my-1.5 w-full cursor-pointer rounded-xl bg-(--gray-2) py-0 transition-colors hover:border-(--gray-7) hover:bg-(--gray-3)",
          wide ? "max-w-full" : "max-w-[660px]",
        )}
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
            {tone && <CiDot tone={tone} />}
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
      className="group relative mx-auto flex h-8 w-full max-w-[900px] items-center gap-2 rounded-md px-2 text-left text-[13px] transition-colors hover:bg-fill-hover"
    >
      <span className="flex size-3.5 shrink-0 items-center justify-center">
        {icon}
      </span>
      <span className="shrink-0 text-muted-foreground text-xs tabular-nums">
        {number}
      </span>
      <span className="min-w-0 flex-1 truncate font-medium">{label}</span>
      {tone && <CiDot tone={tone} />}
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
