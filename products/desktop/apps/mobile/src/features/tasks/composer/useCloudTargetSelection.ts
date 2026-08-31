import { SandboxCustomImagesDisabledError } from "@posthog/api-client/posthog-client";
import { useQuery } from "@tanstack/react-query";
import { useFeatureFlag } from "posthog-react-native";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAuthStore } from "@/features/auth";
import { usePreferencesStore } from "@/features/preferences/stores/preferencesStore";
import { sandboxKeys } from "@/features/tasks/hooks/useCustomImageName";
import { getPostHogApiClient } from "@/lib/posthogApiClient";
import {
  buildCloudTargetOptions,
  type CloudTarget,
  type CloudTargetOption,
  cloudTargetFromKey,
  cloudTargetKey,
  DEFAULT_CLOUD_TARGET,
  moveFavoriteFirst,
  resolveCloudTarget,
} from "./cloudTargets";

const CUSTOM_IMAGES_FEATURE_FLAG = "tasks-modal-vm-sandbox";

export interface UseCloudTargetSelectionResult {
  cloudTarget: CloudTarget;
  setCloudTarget: (target: CloudTarget) => void;
  options: CloudTargetOption[];
  favoriteKey: string | null;
  toggleFavorite: (target: CloudTarget) => void;
  isLoaded: boolean;
}

export function useCloudTargetSelection(): UseCloudTargetSelectionResult {
  const { projectId, oauthAccessToken } = useAuthStore();
  const canQuery = !!projectId && !!oauthAccessToken;
  const imagesFlagEnabled = !!useFeatureFlag(CUSTOM_IMAGES_FEATURE_FLAG);

  const environmentsQuery = useQuery({
    queryKey: sandboxKeys.environments(),
    queryFn: () => getPostHogApiClient().listSandboxEnvironments(),
    enabled: canQuery,
    staleTime: 60_000,
    retry: 0,
  });

  const imagesQuery = useQuery({
    queryKey: sandboxKeys.customImages(),
    queryFn: () => getPostHogApiClient().listSandboxCustomImages(),
    enabled: canQuery && imagesFlagEnabled,
    staleTime: 60_000,
    retry: (failureCount, error) =>
      !(error instanceof SandboxCustomImagesDisabledError) && failureCount < 2,
  });

  const favoriteKey = usePreferencesStore((s) => s.favoriteCloudTargetKey);
  const setFavoriteKey = usePreferencesStore(
    (s) => s.setFavoriteCloudTargetKey,
  );

  const imagesEnabled = imagesFlagEnabled && imagesQuery.data !== undefined;
  const options = useMemo(
    () =>
      moveFavoriteFirst(
        buildCloudTargetOptions({
          environments: environmentsQuery.data ?? [],
          images: imagesQuery.data ?? [],
          imagesEnabled,
        }),
        favoriteKey,
      ),
    [environmentsQuery.data, imagesQuery.data, imagesEnabled, favoriteKey],
  );

  const isLoaded = !environmentsQuery.isLoading && !imagesQuery.isLoading;

  const [cloudTarget, setCloudTargetState] =
    useState<CloudTarget>(DEFAULT_CLOUD_TARGET);
  const didResolveRef = useRef(false);

  useEffect(() => {
    if (didResolveRef.current || !isLoaded) return;
    didResolveRef.current = true;
    setCloudTargetState(
      resolveCloudTarget(cloudTargetFromKey(favoriteKey), options),
    );
  }, [isLoaded, favoriteKey, options]);

  const setCloudTarget = useCallback((target: CloudTarget) => {
    didResolveRef.current = true;
    setCloudTargetState(target);
  }, []);

  const toggleFavorite = useCallback(
    (target: CloudTarget) => {
      const key = cloudTargetKey(target);
      setFavoriteKey(favoriteKey === key ? null : key);
    },
    [favoriteKey, setFavoriteKey],
  );

  return {
    cloudTarget,
    setCloudTarget,
    options,
    favoriteKey,
    toggleFavorite,
    isLoaded,
  };
}
