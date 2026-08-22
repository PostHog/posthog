import {
  CaretDownIcon,
  CaretRightIcon,
  GearSixIcon,
  GitBranchIcon,
  GithubLogoIcon,
  WarningIcon,
} from "@phosphor-icons/react";
import type { GithubRepoAccessSummary } from "@posthog/core/settings/githubRepoSummary";
import { formatRepoPreview } from "@posthog/core/settings/githubRepoSummary";
import { Button, Spinner, Text } from "@posthog/quill";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
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
  /** Secondary line under the account, e.g. "Connected 3 days ago". */
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

  const accessLine = isLoadingRepos ? (
    <Text size="xs" variant="muted">
      Loading repositories…
    </Text>
  ) : hasRepoFetchFailed ? (
    <span className="flex items-center gap-1">
      <WarningIcon
        size={13}
        weight="fill"
        className="shrink-0 text-(--amber-9)"
      />
      <Text size="xs" className="text-(--amber-11)">
        Couldn't load repositories
      </Text>
    </span>
  ) : (
    <Text size="xs" variant="muted" className="truncate">
      {summary.label}
      {canExpand ? (
        <>
          {": "}
          <span className="text-(--gray-12)">{formatRepoPreview(repos)}</span>
        </>
      ) : null}
    </Text>
  );

  return (
    <div className="flex flex-col gap-2 py-3">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 flex-1 items-start gap-3">
          <div className="shrink-0 text-(--gray-11)">
            <GithubLogoIcon size={28} />
          </div>
          <div className="flex min-w-0 flex-col gap-1">
            <Text size="sm">
              <span className="font-medium">
                {status === "unavailable" ? "Removed from" : "Connected to"}
              </span>{" "}
              {onManage ? (
                <button
                  type="button"
                  onClick={onManage}
                  className="cursor-pointer font-medium underline hover:text-(--accent-11)"
                >
                  {accountLabel}
                </button>
              ) : (
                <span className="font-medium">{accountLabel}</span>
              )}
            </Text>
            {meta ? (
              <Text size="xs" variant="muted">
                {meta}
              </Text>
            ) : null}
            <div className="flex min-w-0 items-center gap-2">
              <div className="flex min-w-0 flex-1 items-center gap-1">
                <GitBranchIcon
                  size={13}
                  className="shrink-0 text-(--gray-10)"
                />
                {status === "loading" ? (
                  <Spinner />
                ) : canExpand ? (
                  <button
                    type="button"
                    onClick={() => setExpanded((value) => !value)}
                    className="-mx-1 flex min-w-0 cursor-pointer items-center gap-1 rounded px-1 text-left transition-colors hover:bg-(--gray-3)"
                  >
                    {expanded ? (
                      <CaretDownIcon
                        size={11}
                        className="shrink-0 text-(--gray-10)"
                      />
                    ) : (
                      <CaretRightIcon
                        size={11}
                        className="shrink-0 text-(--gray-10)"
                      />
                    )}
                    {accessLine}
                  </button>
                ) : (
                  accessLine
                )}
              </div>
              {onManage ? (
                <Tooltip content="Manage on GitHub">
                  <Button
                    type="button"
                    variant="outline"
                    size="icon-xs"
                    onClick={onManage}
                    className="shrink-0"
                    aria-label="Manage on GitHub"
                  >
                    <GearSixIcon size={12} />
                  </Button>
                </Tooltip>
              ) : null}
            </div>
          </div>
        </div>
        {actions ? <div className="flex shrink-0 gap-2">{actions}</div> : null}
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
      {status === "unavailable" ? (
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
