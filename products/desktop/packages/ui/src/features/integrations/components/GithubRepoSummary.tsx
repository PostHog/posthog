import {
  ArrowSquareOutIcon,
  CaretDownIcon,
  CaretRightIcon,
  GithubLogoIcon,
  WarningIcon,
} from "@phosphor-icons/react";
import type { GithubRepoAccessSummary } from "@posthog/core/settings/githubRepoSummary";
import { formatRepoPreview } from "@posthog/core/settings/githubRepoSummary";
import { Button, Spinner, Text } from "@posthog/quill";
import type { ReactNode } from "react";
import { useState } from "react";

export type GithubConnectionStatus = "connected" | "unavailable" | "loading";

interface GithubRepoSummaryProps {
  /** The GitHub org or user the installation belongs to. */
  accountLabel: string;
  summary: GithubRepoAccessSummary;
  repos: readonly string[];
  status: GithubConnectionStatus;
  isLoadingRepos?: boolean;
  hasRepoFetchFailed?: boolean;
  /** Appended to the description line, e.g. "Connected 3 days ago". */
  meta?: ReactNode;
  onManage?: () => void;
  /** Slot on the right for the row's actions (Disconnect, Remove...). */
  actions?: ReactNode;
  /** Slot under the row for extra notes or banners. */
  children?: ReactNode;
}

/**
 * One installation row shared by the project connection, the personal installations list and
 * the Self-driving settings, so all three describe repository access the same way.
 */
export function GithubRepoSummary({
  accountLabel,
  summary,
  repos,
  status,
  isLoadingRepos = false,
  hasRepoFetchFailed = false,
  meta,
  onManage,
  actions,
  children,
}: GithubRepoSummaryProps) {
  const [expanded, setExpanded] = useState(false);
  const canExpand = summary.kind !== "all" && repos.length > 0;
  const isUnavailable = status === "unavailable";

  const metaSuffix = meta ? (
    <>
      <span className="mx-0.5">·</span>
      {meta}
    </>
  ) : null;

  const descriptionLine = isLoadingRepos ? (
    <span className="min-w-0">Loading repositories…{metaSuffix}</span>
  ) : hasRepoFetchFailed ? (
    <>
      <WarningIcon
        size={13}
        weight="fill"
        className="shrink-0 text-(--amber-9)"
      />
      <span className="min-w-0 text-(--amber-11)">
        Couldn't load repositories
      </span>
    </>
  ) : canExpand ? (
    <>
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
        className="-mx-1 flex min-w-0 cursor-pointer items-center gap-1 rounded px-1 text-left transition-colors hover:bg-(--gray-3)"
      >
        {expanded ? (
          <CaretDownIcon size={11} className="shrink-0 text-(--gray-10)" />
        ) : (
          <CaretRightIcon size={11} className="shrink-0 text-(--gray-10)" />
        )}
        <span className="min-w-0">
          {summary.label}
          {": "}
          <span className="text-foreground">{formatRepoPreview(repos)}</span>
        </span>
      </button>
      {meta ? <span className="min-w-0">{metaSuffix}</span> : null}
    </>
  ) : (
    <span className="min-w-0">
      {summary.label}
      {metaSuffix}
    </span>
  );

  return (
    <div className="flex flex-col gap-2 px-3.5 py-2.5">
      <div className="flex min-h-11 items-center justify-between gap-6">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <div className="shrink-0 text-(--gray-11)">
            <GithubLogoIcon size={24} />
          </div>
          <div className="flex min-w-0 flex-col gap-0.5">
            <div className="flex min-w-0 items-center gap-1.5">
              <span className="truncate font-medium text-[13px] text-foreground leading-snug">
                {accountLabel}
              </span>
              {isUnavailable ? (
                <span className="shrink-0 rounded-full bg-(--red-3) px-1.5 py-px font-medium text-(--red-11) text-[11px]">
                  Removed from GitHub
                </span>
              ) : null}
            </div>
            <div className="flex min-w-0 items-center gap-1 text-[12px] text-muted-foreground leading-snug">
              {status === "loading" ? <Spinner /> : descriptionLine}
            </div>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {onManage ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onManage}
            >
              Manage
              <ArrowSquareOutIcon size={12} />
            </Button>
          ) : null}
          {actions}
        </div>
      </div>
      {expanded && canExpand ? (
        <div className="ml-9 max-h-48 overflow-y-auto rounded-(--radius-2) border border-(--gray-5) bg-(--gray-2)">
          <div className="flex flex-col py-1">
            {repos.map((repo) => (
              <Text
                key={repo}
                size="xs"
                variant="muted"
                className="truncate px-2 py-0.5"
              >
                {repo}
              </Text>
            ))}
          </div>
        </div>
      ) : null}
      {isUnavailable ? (
        <div className="ml-9 rounded-(--radius-2) border border-(--red-6) bg-(--red-2) px-3 py-2">
          <Text size="xs" className="text-(--red-11)">
            The PostHog app was removed from GitHub. Remove this connection,
            then connect again if you still need it.
          </Text>
        </div>
      ) : null}
      {children}
    </div>
  );
}
