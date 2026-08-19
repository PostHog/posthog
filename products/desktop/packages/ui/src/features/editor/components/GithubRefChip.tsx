import { GithubLogoIcon, GitPullRequestIcon } from "@phosphor-icons/react";
import {
  getPrVisualConfig,
  type PrVisualConfig,
} from "@posthog/core/git-interaction/prStatus";
import {
  Chip,
  cn,
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
  gray: "text-(--gray-11)",
  green: "text-(--green-11)",
  red: "text-(--red-11)",
  purple: "text-(--purple-11)",
};

const CI_STATUS_LABELS = {
  success: "CI passed",
  failure: "CI needs attention",
  pending: "CI running",
  loading: "Loading CI",
} as const;

export interface GithubPrRefDetails {
  state: string | null;
  merged: boolean;
  draft: boolean;
  title: string | null;
  author: string | null;
  ciStatus: keyof typeof CI_STATUS_LABELS | null;
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
  const statusLabel =
    prConfig?.label ??
    (prDetails?.isLoading
      ? "Loading pull request status"
      : "Status unavailable. Open in GitHub.");

  const chip = (
    <a
      {...{ [GITHUB_REF_URL_ATTR]: href }}
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="mx-0.5 inline-flex max-w-full align-middle no-underline"
    >
      <Chip
        size="xs"
        className="cli-file-mention max-w-full cursor-pointer! whitespace-nowrap pl-1 active:translate-y-0"
      >
        <Icon
          size={10}
          weight={kind === "pr" ? "bold" : undefined}
          className={cn(
            "shrink-0",
            prConfig && PR_ICON_TONE_CLASSES[prConfig.color],
          )}
          aria-label={kind === "pr" && prDetails ? statusLabel : undefined}
          aria-hidden={kind === "issue" || !prDetails ? true : undefined}
          role={kind === "pr" && prDetails ? "img" : undefined}
        />
        <span className="min-w-0 truncate">{children}</span>
      </Chip>
    </a>
  );

  if (kind === "issue" || !prDetails) return chip;

  return (
    <Tooltip onOpenChange={onTooltipOpenChange}>
      <TooltipTrigger render={chip} />
      <TooltipContent side="top" className="max-w-80">
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex items-center gap-1.5 font-medium">
            <Icon
              size={12}
              weight="bold"
              className={cn(
                "shrink-0",
                prConfig && PR_ICON_TONE_CLASSES[prConfig.color],
              )}
              aria-hidden="true"
            />
            <span>{statusLabel}</span>
          </div>
          {prDetails.title && (
            <span className="font-medium text-foreground">
              {prDetails.title}
            </span>
          )}
          {(prDetails.author || prDetails.ciStatus) && (
            <span className="flex flex-wrap gap-x-2 text-muted-foreground">
              {prDetails.author && <span>Created by @{prDetails.author}</span>}
              {prDetails.ciStatus && (
                <span>{CI_STATUS_LABELS[prDetails.ciStatus]}</span>
              )}
            </span>
          )}
        </div>
      </TooltipContent>
    </Tooltip>
  );
}
