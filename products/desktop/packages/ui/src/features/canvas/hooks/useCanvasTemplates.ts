import type { CanvasTemplateSummary } from "@posthog/core/canvas/templateSchemas";
import { useHostTRPC } from "@posthog/host-router/react";
import { useQuery } from "@tanstack/react-query";

/** The canvas templates the create-picker offers (built-ins + future user ones). */
export function useCanvasTemplates(): CanvasTemplateSummary[] {
  const trpc = useHostTRPC();
  const { data } = useQuery(
    trpc.canvasTemplates.list.queryOptions(undefined, { staleTime: 60_000 }),
  );
  return data ?? [];
}
