import { GithubLogoIcon, GitPullRequestIcon } from "@phosphor-icons/react";
import {
  getPrVisualConfig,
  type PrVisualConfig,
} from "@posthog/core/git-interaction/prStatus";
import {
  Button,
  cn,
  Skeleton,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { getPrVisualIcon } from "@posthog/ui/features/git-interaction/prIcon";
import type { ReactElement, ReactNode } from "react";

/**
 * DOM attribute carrying the chip's GitHub URL. The conversation context menu
 * reads it (via `closest()`) so "Copy" can copy the link of a right-clicked
 * chip, which is otherwise unreachable from a text selection.
 */
export const GITHUB_REF_URL_ATTR = "data-github-ref-url";

const PR_ICON_TONE_CLASSES: Record<PrVisualConfig["color"], string> = {
  gray: "text-(--gray-11) dark:text-(--gray-11)",
  green: "text-(--green-11) dark:text-(--green-11)",
  red: "text-(--red-11) dark:text-(--red-11)",
  purple: "text-(--purple-11) dark:text-(--purple-11)",
};

/*
 * Skeletons sit on the tooltip's inverted surface, where quill's --muted fill
 * reads as a solid block. Tinting the inherited text color keeps them faint in
 * both themes.
 */
const SKELETON_LINE = "h-3 w-24 rounded-xs bg-current/25";

const CI_STATUS_LABELS = {
  success: "CI passed",
  failure: "CI needs attention",
  pending: "CI running",
} as const;

export type PrRefCiStatus = keyof typeof CI_STATUS_LABELS | "loading";

export interface GithubPrRefDetails {
  state: string | null;
  merged: boolean;
  draft: boolean;
  title: string | null;
  author: string | null;
  ciStatus: PrRefCiStatus | null;
  isLoading: boolean;
}

export function GithubRefChip({
  href,
  kind,
  children,
  prDetails,
  onTooltipOpenChange,
}: {
  href: string;
  kind: "issue" | "pr";
  children: ReactNode;
  prDetails?: GithubPrRefDetails;
  onTooltipOpenChange?: (open: boolean) => void;
}): ReactElement {
  const prConfig =
    prDetails?.state && prDetails.state !== "unknown"
      ? getPrVisualConfig(prDetails.state, prDetails.merged, prDetails.draft)
      : null;
  const Icon =
    kind === "issue"
      ? GithubLogoIcon
      : prConfig
        ? getPrVisualIcon(prConfig.icon)
        : GitPullRequestIcon;
  const statusLabel = prConfig?.label ?? "Status unavailable. Open in GitHub.";
  const isMetaLoading = !prConfig && (prDetails?.isLoading ?? false);
  // The chip shows the state as an icon only, so the screen reader label has to
  // carry the loading state the tooltip renders as a skeleton.
  const iconLabel = isMetaLoading ? "Loading pull request status" : statusLabel;

  const chip = (
    <Button
      variant="outline"
      size="sm"
      // The chip is a link, so it keeps link semantics and Base UI must not
      // expect a native <button>.
      nativeButton={false}
      render={
        <a
          {...{ [GITHUB_REF_URL_ATTR]: href }}
          href={href}
          target="_blank"
          rel="noopener noreferrer"
        />
      }
      className="cli-file-mention focus-visible:-outline-offset-1 mx-0.5 max-w-full cursor-pointer! whitespace-nowrap pl-1.5 align-baseline no-underline"
    >
      <Icon
        size={12}
        weight={kind === "pr" ? "bold" : undefined}
        className={cn(
          "shrink-0",
          prConfig && PR_ICON_TONE_CLASSES[prConfig.color],
        )}
        aria-label={kind === "pr" && prDetails ? iconLabel : undefined}
        aria-hidden={kind === "issue" || !prDetails ? true : undefined}
        role={kind === "pr" && prDetails ? "img" : undefined}
      />
      <span
        className={cn(
          "min-w-0 max-w-64 truncate",
          prConfig && PR_ICON_TONE_CLASSES[prConfig.color],
        )}
      >
        {children}
      </span>
    </Button>
  );

  if (kind === "issue" || !prDetails) return chip;

  return (
    <Tooltip onOpenChange={onTooltipOpenChange}>
      <TooltipTrigger render={chip} />
      <TooltipContent side="top" className="max-w-80 py-2">
        {/* The tooltip surface is inverted, so its contents inherit that color
            rather than the page foreground/muted tokens. */}
        <div className="flex min-w-0 flex-col gap-1.5 text-start">
          <div className="flex items-center gap-1.5 font-medium">
            <Icon
              size={12}
              weight="bold"
              className="shrink-0"
              aria-hidden="true"
            />
            {isMetaLoading ? (
              <Skeleton className={SKELETON_LINE} />
            ) : (
              <span>{statusLabel}</span>
            )}
          </div>
          {prDetails.title ? (
            <span className="line-clamp-2 font-medium">{prDetails.title}</span>
          ) : (
            isMetaLoading && <Skeleton className={cn(SKELETON_LINE, "w-56")} />
          )}
          {(isMetaLoading || prDetails.author || prDetails.ciStatus) && (
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-current/70">
              {isMetaLoading ? (
                <Skeleton className={cn(SKELETON_LINE, "w-28")} />
              ) : (
                prDetails.author && <span>Created by @{prDetails.author}</span>
              )}
              {prDetails.ciStatus === "loading" ? (
                <Skeleton className={cn(SKELETON_LINE, "w-16")} />
              ) : (
                prDetails.ciStatus && (
                  <span>{CI_STATUS_LABELS[prDetails.ciStatus]}</span>
                )
              )}
            </span>
          )}
        </div>
      </TooltipContent>
    </Tooltip>
  );
}
