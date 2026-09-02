import {
  Check,
  GitMerge,
  GitPullRequest,
  type Icon,
  PencilSimple,
  X,
} from "@phosphor-icons/react";
import type { PrVisualIcon } from "@posthog/core/git-interaction/prStatus";
import type { PrActionType } from "@posthog/shared";

export function getPrVisualIcon(icon: PrVisualIcon): Icon {
  switch (icon) {
    case "merged":
      return GitMerge;
    case "pull-request":
      return GitPullRequest;
  }
}

export function getPrActionIcon(action: PrActionType): React.ReactNode {
  switch (action) {
    case "close":
      return <X size={12} weight="bold" />;
    case "reopen":
      return <GitPullRequest size={12} weight="bold" />;
    case "ready":
      return <Check size={12} weight="bold" />;
    case "draft":
      return <PencilSimple size={12} weight="bold" />;
  }
}
