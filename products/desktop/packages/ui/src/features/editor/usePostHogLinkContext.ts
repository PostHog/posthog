import type { PostHogLinkContext } from "@posthog/core/posthog-objects/objectUrls";
import { getCloudUrlFromRegion } from "@posthog/shared";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { remarkObjectTags } from "@posthog/ui/utils/remarkObjectTags";
import { useMemo } from "react";
import remarkGfm from "remark-gfm";
import type { PluggableList } from "unified";

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

export function useObjectTagRemarkPlugins(): PluggableList {
  const links = usePostHogLinkContext();
  return useMemo(() => [remarkGfm, [remarkObjectTags, { links }]], [links]);
}
