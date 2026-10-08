import type { LoopSchemas } from "@posthog/api-client/loops";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useMemo } from "react";
import { type LoopScope, resolveLoopScope } from "../loopScopes";

export function useLoopScope(
  loop: LoopSchemas.Loop | undefined,
): LoopScope | null {
  const { channels } = useChannels();
  return useMemo(
    () => (loop ? resolveLoopScope(loop, channels) : null),
    [loop, channels],
  );
}
