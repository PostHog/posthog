import { useService } from "@posthog/di/react";
import {
  PREVIEW_DEPLOYMENT,
  type PreviewDeploymentInfo,
} from "@posthog/platform/preview-deployment";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";

/**
 * Persistent preview identifier shown by preview builds: the PR number and
 * short commit SHA of the backend this installer tests. Ordinary builds bind
 * no preview deployment and render nothing.
 *
 * Clicking opens the backend in a browser (the hibernation wake path and the
 * "download a fresh installer after a push" check both start there).
 */
export function PreviewBadge() {
  const preview = useService<PreviewDeploymentInfo | null>(PREVIEW_DEPLOYMENT);
  if (!preview) {
    return null;
  }
  return (
    <Tooltip content="Open this pull request's preview backend in a browser">
      <button
        type="button"
        onClick={() => void openExternalUrl(preview.manifest.backendOrigin)}
        className="rounded-(--radius-3) border border-(--gray-6) px-2 py-1 text-(--gray-10) text-xs transition-colors hover:text-(--gray-12)"
      >
        Preview {preview.label}
      </button>
    </Tooltip>
  );
}
