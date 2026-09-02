import { useHostTRPC } from "@posthog/host-router/react";
import { Button, Progress } from "@posthog/quill";
import {
  ANALYTICS_EVENTS,
  type AnnouncementProperties,
} from "@posthog/shared/analytics-events";
import {
  useInstallUpdate,
  useUpdateView,
} from "@posthog/ui/features/updates/updateStore";
import { track } from "@posthog/ui/shell/analytics";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

const MANUAL_DOWNLOAD_URL =
  "https://github.com/PostHog/posthog/releases?q=desktop";

/**
 * The announcement-side entry into the existing update flow: kicks a check,
 * then walks available → downloading → restart. Where the updater is
 * unavailable (Linux, dev builds), degrades to a manual-download link.
 */
export function UpdateAction({
  analytics,
  showProgress = false,
  onInstallHandoff,
  onInstallFailed,
}: {
  analytics: AnnouncementProperties;
  showProgress?: boolean;
  /**
   * Fired when the restart-to-install handoff begins — the last point before
   * the app quits to apply the update. Blocking announcements record their
   * acknowledgement here, not on earlier clicks: a failed or abandoned
   * download must keep the announcement blocking. The manual-download link
   * never fires this — a browser download can't confirm an install, so
   * retirement is left to the version gate after relaunch.
   */
  onInstallHandoff?: () => void;
  /**
   * The handoff's companion: fired when the install fails before the app
   * quits, so state committed at the handoff (an acknowledgement) can be
   * reverted. On success the app is gone before this could fire.
   */
  onInstallFailed?: () => void;
}) {
  const { status, isEnabled, downloadPercent } = useUpdateView();
  const installUpdate = useInstallUpdate();
  const hostTRPC = useHostTRPC();
  // The updater's async failures aren't exposed through useUpdateView (a
  // failed download collapses back to idle), so failures are tracked here:
  // mutation errors directly, stream failures via the downloading→idle
  // transition below. Without this a failed download silently re-renders
  // the ordinary "Check for updates" state.
  const [actionError, setActionError] = useState<string | null>(null);
  const { mutate: runCheck, isPending: isCheckPending } = useMutation({
    ...hostTRPC.updates.check.mutationOptions(),
    onError: () => setActionError("Couldn't check for updates."),
  });
  const { mutate: runDownload, isPending: isDownloadPending } = useMutation({
    ...hostTRPC.updates.download.mutationOptions(),
    onError: () => setActionError("The download failed."),
  });

  const previousStatus = useRef(status);
  useEffect(() => {
    const previous = previousStatus.current;
    previousStatus.current = status;
    if (previous === "downloading" && status === "idle") {
      setActionError("The download didn't finish.");
    } else if (status !== "idle") {
      setActionError(null);
    }
  }, [status]);

  // This surface exists because an update is wanted, so make the state
  // actionable immediately instead of waiting for the hourly poll.
  const kicked = useRef(false);
  useEffect(() => {
    if (!isEnabled || kicked.current || status !== "idle") return;
    kicked.current = true;
    runCheck(undefined);
  }, [isEnabled, status, runCheck]);

  const trackClick = () => {
    track(ANALYTICS_EVENTS.ANNOUNCEMENT_CTA_CLICKED, {
      ...analytics,
      cta_type: "update",
    });
  };

  if (!isEnabled) {
    return (
      <Button
        variant="primary"
        size="sm"
        onClick={() => {
          trackClick();
          openExternalUrl(MANUAL_DOWNLOAD_URL);
        }}
      >
        Download the latest version
      </Button>
    );
  }

  if (status === "ready" || status === "installing") {
    return (
      <Button
        variant="primary"
        size="sm"
        disabled={status === "installing"}
        onClick={() => {
          trackClick();
          onInstallHandoff?.();
          void installUpdate().then((installed) => {
            if (!installed) onInstallFailed?.();
          });
        }}
      >
        Restart to update
      </Button>
    );
  }

  if (status === "downloading") {
    const percent = Math.round(downloadPercent ?? 0);
    if (showProgress) {
      return (
        <div className="flex min-w-40 flex-col gap-1">
          <span className="text-[11px] text-gray-11">
            Downloading… {percent}%
          </span>
          <Progress value={percent} />
        </div>
      );
    }
    return (
      <Button variant="outline" size="sm" disabled>
        Downloading… {percent}%
      </Button>
    );
  }

  if (status === "available") {
    return (
      <Button
        variant="primary"
        size="sm"
        disabled={isDownloadPending}
        onClick={() => {
          trackClick();
          runDownload(undefined);
        }}
      >
        Update now
      </Button>
    );
  }

  if (status === "checking" || isCheckPending) {
    return (
      <Button variant="outline" size="sm" disabled>
        Checking for updates…
      </Button>
    );
  }

  // Idle after the kicked check means it found nothing or failed — leave the
  // user a way to retry, and say so when we know something went wrong.
  return (
    <div className="flex flex-col items-end gap-1">
      {actionError && (
        <span className="text-(--red-11) text-[11px]">{actionError}</span>
      )}
      <Button
        variant="outline"
        size="sm"
        onClick={() => {
          setActionError(null);
          runCheck(undefined);
        }}
      >
        {actionError ? "Try again" : "Check for updates"}
      </Button>
    </div>
  );
}
