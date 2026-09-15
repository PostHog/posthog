import {
  getAuthIdentity,
  useAuthStateValue,
} from "@posthog/ui/features/auth/store";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { useInboxReportReadStore } from "@posthog/ui/features/inbox/stores/inboxReportReadStore";
import { useCallback } from "react";

export function useInboxReportReadState(reportId: string): {
  isUnread: boolean;
  enabled: boolean;
  setRead: (read: boolean) => void;
} {
  const identity = useAuthStateValue(getAuthIdentity);
  const { data: user } = useCurrentUser();
  const key =
    identity && user?.uuid
      ? JSON.stringify([identity, user.uuid, reportId])
      : null;
  const hasHydrated = useInboxReportReadStore((state) => state.hasHydrated);
  const isRead = useInboxReportReadStore(
    (state) => key !== null && state.readByKey[key] === true,
  );
  const setStoredRead = useInboxReportReadStore((state) => state.setRead);
  const setRead = useCallback(
    (read: boolean) => {
      if (key !== null) setStoredRead(key, read);
    },
    [key, setStoredRead],
  );
  const enabled = key !== null && hasHydrated;
  return { isUnread: enabled && !isRead, enabled, setRead };
}
