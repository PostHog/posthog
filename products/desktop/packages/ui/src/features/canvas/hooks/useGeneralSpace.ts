import {
  useChannelMutations,
  useChannels,
} from "@posthog/ui/features/canvas/hooks/useChannels";
import { toast } from "@posthog/ui/primitives/toast";
import { useEffect, useRef, useState } from "react";

export const GENERAL_SPACE_NAME = "general";

export function useGeneralSpace(): {
  generalSpaceId: string | null;
  isLoading: boolean;
} {
  const { channels, isLoading } = useChannels();
  const { createChannel } = useChannelMutations();
  const creationStarted = useRef(false);
  const [creationFailed, setCreationFailed] = useState(false);
  const generalSpace = channels.find(
    (channel) =>
      channel.channelType === "public" && channel.name === GENERAL_SPACE_NAME,
  );

  useEffect(() => {
    if (isLoading || generalSpace || creationStarted.current || creationFailed)
      return;
    creationStarted.current = true;
    void createChannel(GENERAL_SPACE_NAME).catch((error: unknown) => {
      creationStarted.current = false;
      setCreationFailed(true);
      toast.error("Couldn't create the general space", {
        description:
          error instanceof Error
            ? error.message
            : "Refresh the page to try again.",
      });
    });
  }, [createChannel, creationFailed, generalSpace, isLoading]);

  return {
    generalSpaceId: generalSpace?.id ?? null,
    isLoading: isLoading || (!generalSpace && !creationFailed),
  };
}
