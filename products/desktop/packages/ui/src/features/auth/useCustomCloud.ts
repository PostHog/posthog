import { useHostTRPCClient } from "@posthog/host-router/react";
import {
  type CustomCloud,
  configureCustomCloud,
  normalizeCustomCloud,
} from "@posthog/shared";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

export type CustomCloudDraft = Record<keyof CustomCloud, string>;

const EMPTY_DRAFT: CustomCloudDraft = {
  url: "",
  oauthClientId: "",
  gatewayUrl: "",
};

const CUSTOM_CLOUD_QUERY_KEY = ["customCloud"] as const;

const URL_SHAPE_MESSAGE =
  "with no path, query, or fragment, and not a PostHog Cloud address";

export function useCustomCloud({ enabled }: { enabled: boolean }) {
  const hostClient = useHostTRPCClient();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<CustomCloudDraft>(EMPTY_DRAFT);
  const [error, setError] = useState<string | null>(null);

  const stored = useQuery({
    queryKey: CUSTOM_CLOUD_QUERY_KEY,
    queryFn: () => hostClient.customCloud.get.query(),
    enabled,
  });

  useEffect(() => {
    if (!stored.data) return;
    setDraft({
      url: stored.data.url,
      oauthClientId: stored.data.oauthClientId ?? "",
      gatewayUrl: stored.data.gatewayUrl ?? "",
    });
  }, [stored.data]);

  const save = useMutation({
    mutationKey: CUSTOM_CLOUD_QUERY_KEY,
    mutationFn: (target: CustomCloud) =>
      hostClient.customCloud.set.mutate(target),
    onSuccess: (saved) => {
      configureCustomCloud(saved);
      queryClient.setQueryData(CUSTOM_CLOUD_QUERY_KEY, saved);
    },
  });

  const updateDraft = (patch: Partial<CustomCloudDraft>) => {
    setError(null);
    setDraft((current) => ({ ...current, ...patch }));
  };

  const commit = async (): Promise<boolean> => {
    if (!draft.url.trim()) {
      setError("Enter the URL of your PostHog instance");
      return false;
    }
    if (!draft.oauthClientId.trim()) {
      setError("Enter the client ID of the OAuth application on that instance");
      return false;
    }
    const target = normalizeCustomCloud(draft);
    if (!target) {
      setError(`Enter the full URL of the instance, ${URL_SHAPE_MESSAGE}`);
      return false;
    }
    if (draft.gatewayUrl.trim() && !target.gatewayUrl) {
      setError(`Enter the full URL of the gateway, ${URL_SHAPE_MESSAGE}`);
      return false;
    }
    try {
      await save.mutateAsync(target);
    } catch {
      setError("Could not save these settings. Try again.");
      return false;
    }
    return true;
  };

  return {
    draft,
    updateDraft,
    commit,
    error,
    isSaving: save.isPending,
  };
}
