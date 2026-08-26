import { GitPullRequestIcon } from "@phosphor-icons/react";
import { getPrVisualConfig } from "@posthog/core/git-interaction/prStatus";
import {
  cn,
  Skeleton,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { GithubRefChipLink } from "@posthog/ui/features/editor/components/GithubRefChip";
import { getPrVisualIcon } from "@posthog/ui/features/git-interaction/prIcon";
import { PR_TONE_TEXT } from "@posthog/ui/features/git-interaction/prTone";
import type { ReactElement, ReactNode } from "react";

const CI_STATUS_LABELS = {
  success: "CI passed",
  failure: "CI needs attention",
  pending: "CI running",
} as const;

export type PrCiStatus = keyof typeof CI_STATUS_LABELS;

export interface PrRefDetails {
  state: string | null;
  merged: boolean;
  draft: boolean;
  title: string | null;
  author: string | null;
  isLoading: boolean;
  ciStatus: PrCiStatus | null;
  isCiLoading: boolean;
}

/*
 * Skeletons sit on the tooltip's inverted surface, where quill's --muted fill
 * reads as a solid block. Tinting the inherited text color keeps them faint in
 * both themes.
 */
const SKELETON_LINE = "h-3 w-24 rounded-xs bg-current/25";

/**
 * A pull request chip that reports the PR's lifecycle: a tinted icon on the
 * chip, and title, creator, and CI status in the hover card. Presentational —
 * `GithubPrRefChip` supplies the details.
 */
export function PrRefChip({
  href,
  details,
  onTooltipOpenChange,
  children,
}: {
  href: string;
  details: PrRefDetails;
  onTooltipOpenChange?: (open: boolean) => void;
  children: ReactNode;
}): ReactElement {
  const config =
    details.state && details.state !== "unknown"
      ? getPrVisualConfig(details.state, details.merged, details.draft)
      : null;
  const isLoading = !config && details.isLoading;
  const statusLabel = config?.label ?? "Status unavailable. Open in GitHub.";
  // The chip shows the state as an icon only, so the screen reader label has to
  // carry the loading state the tooltip renders as a skeleton.
  const iconLabel = isLoading ? "Loading pull request status" : statusLabel;
  const StatusIcon = config ? getPrVisualIcon(config.icon) : GitPullRequestIcon;
  const toneClass = config ? PR_TONE_TEXT[config.color] : undefined;

  return (
    <Tooltip onOpenChange={onTooltipOpenChange}>
      <TooltipTrigger
        render={
          <GithubRefChipLink
            href={href}
            icon={StatusIcon}
            iconLabel={iconLabel}
            toneClass={toneClass}
          >
            {children}
          </GithubRefChipLink>
        }
      />
      <TooltipContent side="top" className="max-w-80 py-2">
        {/* The tooltip surface is inverted, so its contents inherit that color
            rather than the page foreground/muted tokens. */}
        <div className="flex min-w-0 flex-col gap-1.5 text-start">
          <div className="flex items-center gap-1.5 font-medium">
            <StatusIcon
              size={12}
              weight="bold"
              className="shrink-0"
              aria-hidden="true"
            />
            {isLoading ? (
              <Skeleton className={SKELETON_LINE} />
            ) : (
              <span>{statusLabel}</span>
            )}
          </div>
          {details.title ? (
            <span className="line-clamp-2 font-medium">{details.title}</span>
          ) : (
            isLoading && <Skeleton className={cn(SKELETON_LINE, "w-56")} />
          )}
          {(isLoading ||
            details.author ||
            details.ciStatus ||
            details.isCiLoading) && (
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-current/70">
              {isLoading ? (
                <Skeleton className={cn(SKELETON_LINE, "w-28")} />
              ) : (
                details.author && <span>Created by @{details.author}</span>
              )}
              {details.isCiLoading ? (
                <Skeleton className={cn(SKELETON_LINE, "w-16")} />
              ) : (
                details.ciStatus && (
                  <span>{CI_STATUS_LABELS[details.ciStatus]}</span>
                )
              )}
            </span>
          )}
        </div>
      </TooltipContent>
    </Tooltip>
  );
}
