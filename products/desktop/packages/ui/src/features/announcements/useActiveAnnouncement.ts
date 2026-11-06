import { useHostTRPC } from "@posthog/host-router/react";
import { ANNOUNCEMENTS_FLAG } from "@posthog/shared";
import { logger } from "@posthog/ui/shell/logger";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useFeatureFlag } from "../feature-flags/useFeatureFlag";
import { useFeatureFlagPayload } from "../feature-flags/useFeatureFlagPayload";
import { useAnnouncementsStore } from "./announcementsStore";
import {
  type ActiveAnnouncement,
  selectAnnouncement,
} from "./selectAnnouncement";

const log = logger.scope("announcements");

export function useActiveAnnouncement(): ActiveAnnouncement | null {
  const armed = useFeatureFlag(ANNOUNCEMENTS_FLAG);
  const payload = useFeatureFlagPayload(ANNOUNCEMENTS_FLAG);
  const hostTRPC = useHostTRPC();
  const { data: appVersion } = useQuery(
    hostTRPC.os.getAppVersion.queryOptions(),
  );
  const dismissedIds = useAnnouncementsStore((state) => state.dismissedIds);
  const handledThisSession = useAnnouncementsStore(
    (state) => state.handledThisSession,
  );
  const hasHydrated = useAnnouncementsStore((state) => state._hasHydrated);
  const [now, setNow] = useState(() => Date.now());

  const dismissedSet = useMemo(
    () => new Set(Object.keys(dismissedIds)),
    [dismissedIds],
  );
  const result = useMemo(
    () =>
      selectAnnouncement({
        payload,
        now,
        appVersion: appVersion ?? null,
        isDevBuild: import.meta.env.DEV,
        dismissedIds: dismissedSet,
        handledThisSession,
      }),
    [payload, now, appVersion, dismissedSet, handledThisSession],
  );

  // A scheduled item can cross its startsAt/endsAt while the app sits open;
  // a minute of slack is fine for announcements, so tick only then.
  useEffect(() => {
    if (!result.hasSchedule) return;
    const interval = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(interval);
  }, [result.hasSchedule]);

  const lastLoggedPayload = useRef<unknown>(undefined);
  useEffect(() => {
    if (payload === undefined || lastLoggedPayload.current === payload) return;
    lastLoggedPayload.current = payload;
    if (result.parseError) {
      log.error("Announcements flag payload failed to parse");
    } else if (result.invalidItems > 0) {
      log.warn(
        `Dropped ${result.invalidItems} invalid announcement(s) from flag payload`,
      );
    }
  }, [payload, result]);

  if (!armed || !hasHydrated) return null;
  return result.active;
}
