import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import {
  useChannelMutations,
  useChannels,
} from "@posthog/ui/features/canvas/hooks/useChannels";
import { toast } from "@posthog/ui/primitives/toast";
import { useEffect, useRef, useState } from "react";

export const DEFAULT_REPORT_SPACE_NAME = "general";

export function useReportSpace(enabled = true): {
  reportSpaceId: string | null;
  isLoading: boolean;
} {
  const { channels, isLoading } = useChannels();
  const { createChannel } = useChannelMutations();
  const currentProjectId = useAuthStateValue((state) => state.currentProjectId);
  const creationStarted = useRef(false);
  const provisioningProjectId = useRef(currentProjectId);
  const [creationFailed, setCreationFailed] = useState(false);
  const reportSpace = channels.find(
    (channel) =>
      channel.channelType === "public" &&
      channel.name === DEFAULT_REPORT_SPACE_NAME,
  );

  useEffect(() => {
    if (provisioningProjectId.current === currentProjectId) return;
    provisioningProjectId.current = currentProjectId;
    creationStarted.current = false;
    setCreationFailed(false);
  }, [currentProjectId]);

  useEffect(() => {
    if (
      provisioningProjectId.current !== currentProjectId ||
      !enabled ||
      isLoading ||
      reportSpace ||
      creationStarted.current ||
      creationFailed
    )
      return;
    creationStarted.current = true;
    void createChannel(DEFAULT_REPORT_SPACE_NAME, { star: true }).catch(
      (error: unknown) => {
        creationStarted.current = false;
        setCreationFailed(true);
        toast.error("Couldn't create the report space", {
          // Stable id so concurrent hook instances collapse to one toast
          // instead of stacking identical failures.
          id: "report-space-creation-error",
          description:
            error instanceof Error
              ? error.message
              : "Refresh the page to try again.",
        });
      },
    );
  }, [
    createChannel,
    creationFailed,
    currentProjectId,
    enabled,
    isLoading,
    reportSpace,
  ]);

  return {
    reportSpaceId: enabled ? (reportSpace?.id ?? null) : null,
    isLoading: enabled && (isLoading || (!reportSpace && !creationFailed)),
  };
}
