import {
  getAuthIdentity,
  useAuthStateValue,
} from "@posthog/ui/features/auth/store";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { useInboxReportReadStore } from "@posthog/ui/features/inbox/stores/inboxReportReadStore";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { toast } from "@posthog/ui/primitives/toast";
import { useQueryClient } from "@tanstack/react-query";
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
  const queryClient = useQueryClient();
  const queryKey = ["report-read", identity, user?.uuid, reportId];
  const synced = useAuthenticatedQuery(
    queryKey,
    (client) => client.getReportReadState(reportId),
    {
      enabled: !!key,
      staleTime: 15_000,
      refetchInterval: 30_000,
    },
  );
  const { mutate } = useAuthenticatedMutation(
    (client, read: boolean) => client.getReportReadStates([reportId], read),
    {
      scope: { id: JSON.stringify(queryKey) },
      onMutate: async (read) => {
        await queryClient.cancelQueries({ queryKey });
        const previous = queryClient.getQueryData<boolean>(queryKey);
        queryClient.setQueryData(queryKey, read);
        return { previous };
      },
      onSuccess: (states) => {
        queryClient.setQueryData(queryKey, states[reportId]);
        if (key) setStoredRead(key, states[reportId]);
      },
      onError: (_error, _read, context) => {
        queryClient.setQueryData(queryKey, context?.previous ?? false);
        void queryClient.invalidateQueries({ queryKey });
        toast.error("Could not sync report read state. Try again.");
      },
    },
  );
  const hasHydrated = useInboxReportReadStore((state) => state.hasHydrated);
  const isRead = useInboxReportReadStore(
    (state) => key !== null && state.readByKey[key] === true,
  );
  const setStoredRead = useInboxReportReadStore((state) => state.setRead);
  const setRead = useCallback(
    (read: boolean) => {
      if (key !== null) mutate(read);
    },
    [key, mutate],
  );
  const enabled = key !== null && hasHydrated;
  return { isUnread: enabled && !(synced.data ?? isRead), enabled, setRead };
}
