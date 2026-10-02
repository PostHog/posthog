import type { PostHogLinkContext } from "@posthog/core/posthog-objects/objectUrls";
import { getCloudUrlFromRegion } from "@posthog/shared";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useMemo } from "react";

export function usePostHogLinkContext(): PostHogLinkContext | null {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);
  return useMemo(
    () =>
      cloudRegion && projectId
        ? { appUrl: getCloudUrlFromRegion(cloudRegion), projectId }
        : null,
    [cloudRegion, projectId],
  );
}
