import { isEnrichmentEligible } from "@posthog/core/code-editor/enrichmentEligibility";
import { useHostTRPC } from "@posthog/host-router/react";
import type { SerializedEnrichment } from "@posthog/shared";
import { useQuery } from "@tanstack/react-query";
import { useAuthStateValue } from "../../auth/store";

interface UseFileEnrichmentOptions {
  taskId: string;
  filePath: string;
  absolutePath?: string;
  content: string | null | undefined;
}

export function useFileEnrichment({
  taskId,
  filePath,
  absolutePath,
  content,
}: UseFileEnrichmentOptions): SerializedEnrichment | null {
  const trpc = useHostTRPC();
  const isAuthenticated = useAuthStateValue(
    (s) => s.status === "authenticated",
  );

  const eligible = isEnrichmentEligible(filePath, content);

  const query = useQuery(
    trpc.enrichment.enrichFile.queryOptions(
      {
        taskId,
        filePath,
        absolutePath,
        content: content ?? "",
      },
      {
        enabled: eligible && isAuthenticated,
        staleTime: Number.POSITIVE_INFINITY,
      },
    ),
  );

  return query.data ?? null;
}
