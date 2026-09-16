import { ANALYTICS_EVENTS } from "@posthog/shared";
import {
  isHintRetired,
  useSettingsStore,
} from "@posthog/ui/features/settings/settingsStore";
import { TIP_KEYS } from "@posthog/ui/features/settings/tipKeys";
import { settingsSourceHref } from "@posthog/ui/router/reportNavigation";
import { track } from "@posthog/ui/shell/analytics";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
import { Link } from "@tanstack/react-router";
import { useEffect, useRef } from "react";
import { type PermissionToolCall, permissionKind } from "./types";

const TIP_KEY = TIP_KEYS.bypassPermissionsMode;

/**
 * Points at the setting that ends the approvals, from the prompt asking for
 * one. Without it the way out is only reachable by someone who already knows
 * the mode exists, so the answer to a long run of Allow clicks is more
 * clicking. Silent once bypass is allowed: the mode menu teaches it from there.
 */
export function BypassPermissionsHint({
  toolCall,
}: {
  toolCall: PermissionToolCall;
}) {
  const { localWorkspaces } = useHostCapabilities();
  const allowBypassPermissions = useSettingsStore(
    (state) => state.allowBypassPermissions,
  );
  const tipsEnabled = useSettingsStore((state) => state.tipsEnabled);
  const hint = useSettingsStore((state) => state.hints[TIP_KEY]);
  // Wait for persisted answers, or a restart would flash an answered hint.
  const hydrated = useSettingsStore((state) => state._hasHydrated);
  // Spending this prompt's showing must not take the hint away mid-prompt, so
  // an offer made stands until the dock closes.
  const offered = useRef(false);

  const wanted =
    // A question is addressed to the person, so no mode answers it for them.
    permissionKind(toolCall) !== "question" &&
    // The web host hides the harness settings the link points at.
    localWorkspaces &&
    hydrated &&
    !allowBypassPermissions;
  const showing =
    wanted &&
    (offered.current || (tipsEnabled && !isHintRetired(TIP_KEY, hint)));

  useEffect(() => {
    if (!showing || offered.current) return;
    offered.current = true;
    useSettingsStore.getState().recordHintShown(TIP_KEY);
  }, [showing]);

  if (!showing) return null;

  return (
    <p className="px-2 pt-2 text-muted-foreground text-xs">
      Approving every step?{" "}
      <Link
        to="/settings/$category"
        params={{ category: "harness" }}
        search={{ from: settingsSourceHref() }}
        onClick={() => {
          track(ANALYTICS_EVENTS.PERMISSION_BYPASS_HINT_OPENED);
          useSettingsStore.getState().markHintLearned(TIP_KEY);
        }}
        className="text-foreground underline underline-offset-2"
      >
        Allow bypass permissions
      </Link>{" "}
      in settings, then pick that mode to let a session run without asking.
      Codex calls the mode Full access.
    </p>
  );
}
