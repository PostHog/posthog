import type { VisionScanner } from "@posthog/api-client/posthog-client";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { toast } from "@posthog/ui/primitives/toast";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";

const SCANNERS_QUERY_KEY = "vision-scanners";

/**
 * Replay Vision scanners and their per-scanner `emits_signals` flag.
 *
 * Replay Vision has no `SignalSourceConfig` row: each scanner authorizes itself, so this list
 * is the only place the source can be switched on or off.
 */
export function useVisionScanners() {
  const client = useAuthenticatedClient();
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const queryClient = useQueryClient();
  const { data, isLoading } = useAuthenticatedQuery<VisionScanner[]>(
    ["signals", SCANNERS_QUERY_KEY, projectId],
    (authedClient) =>
      projectId
        ? authedClient.listVisionScanners(projectId)
        : Promise.resolve([]),
    {
      enabled: !!projectId,
      staleTime: 30_000,
    },
  );

  const pendingRef = useRef(new Set<string>());
  const [togglingScanners, setTogglingScanners] = useState<
    Record<string, boolean>
  >({});

  const handleToggleScanner = useCallback(
    async (scannerId: string) => {
      if (!client || !projectId) return;
      if (pendingRef.current.has(scannerId)) return;
      const scanner = data?.find((candidate) => candidate.id === scannerId);
      if (!scanner) return;

      pendingRef.current.add(scannerId);
      setTogglingScanners((prev) => ({ ...prev, [scannerId]: true }));
      try {
        await client.updateVisionScannerSignals(
          projectId,
          scannerId,
          !(scanner.emits_signals ?? false),
        );
        await queryClient.invalidateQueries({
          queryKey: ["signals", SCANNERS_QUERY_KEY, projectId],
        });
      } catch (error: unknown) {
        toast.error(
          error instanceof Error
            ? error.message
            : `Failed to switch ${scanner.name}`,
        );
      } finally {
        pendingRef.current.delete(scannerId);
        setTogglingScanners((prev) => {
          const next = { ...prev };
          delete next[scannerId];
          return next;
        });
      }
    },
    [client, projectId, data, queryClient],
  );

  return {
    scanners: data ?? [],
    scannersLoading: isLoading,
    togglingScanners,
    handleToggleScanner,
  };
}
