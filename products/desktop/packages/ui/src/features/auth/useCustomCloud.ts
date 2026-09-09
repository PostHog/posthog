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
  gatewayToken: "",
};

const CUSTOM_CLOUD_QUERY_KEY = ["customCloud"] as const;

export function useCustomCloud() {
  const hostClient = useHostTRPCClient();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<CustomCloudDraft>(EMPTY_DRAFT);
  const [error, setError] = useState<string | null>(null);

  const stored = useQuery({
    queryKey: CUSTOM_CLOUD_QUERY_KEY,
    queryFn: () => hostClient.customCloud.get.query(),
  });

  useEffect(() => {
    if (!stored.data) return;
    configureCustomCloud(stored.data);
    setDraft({
      url: stored.data.url,
      oauthClientId: stored.data.oauthClientId ?? "",
      gatewayUrl: stored.data.gatewayUrl ?? "",
      gatewayToken: stored.data.gatewayToken ?? "",
    });
  }, [stored.data]);

  const save = useMutation({
    mutationFn: (target: CustomCloud | null) =>
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
      await save.mutateAsync(null);
      return true;
    }
    const target = normalizeCustomCloud(draft);
    const rejected = (["url", "gatewayUrl"] as const).find(
      (field) => draft[field].trim() && !target?.[field],
    );
    if (!target || rejected) {
      setError(
        `Enter the full URL of the ${rejected === "gatewayUrl" ? "gateway" : "instance"}, with http:// or https://`,
      );
      return false;
    }
    await save.mutateAsync(target);
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
