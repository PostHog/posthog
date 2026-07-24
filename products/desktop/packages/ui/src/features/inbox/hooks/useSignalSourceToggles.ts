import type { SignalSourceConfig } from "@posthog/api-client/posthog-client";
import {
  ANALYTICS_EVENTS,
  EXTERNAL_INBOX_SOURCES,
  type SignalRecordKind,
  sourceNeedsFullRefresh,
} from "@posthog/shared";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import type { SignalSourceValues } from "@posthog/ui/features/inbox/components/SignalSourceToggles";
import { useExternalDataSources } from "@posthog/ui/features/inbox/hooks/useExternalDataSources";
import { useSignalSourceConfigs } from "@posthog/ui/features/inbox/hooks/useSignalSourceConfigs";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useRef, useState } from "react";

type SourceType = SignalSourceConfig["source_type"];
type SourceKey = keyof SignalSourceValues;

// Non-warehouse toggles are hard-wired; every warehouse source is derived from the shared
// EXTERNAL_INBOX_SOURCES registry so adding a source is a one-line change there.
const SOURCE_TYPE_MAP: Partial<Record<SourceKey, SourceType>> = {
  conversations: "ticket",
  health_checks: "health_issue",
  session_replay: "session_analysis_cluster",
  ...Object.fromEntries(
    EXTERNAL_INBOX_SOURCES.map((s) => [s.product, s.recordKind]),
  ),
};

const ERROR_TRACKING_SOURCE_TYPES: SourceType[] = [
  "issue_created",
  "issue_reopened",
  "issue_spiking",
];

const SOURCE_LABELS: Partial<Record<SourceKey, string>> = {
  conversations: "PostHog Support",
  error_tracking: "Error tracking",
  health_checks: "Health checks",
  session_replay: "Session replay",
  ...Object.fromEntries(
    EXTERNAL_INBOX_SOURCES.map((s) => [s.product, s.label]),
  ),
};

const DATA_WAREHOUSE_SOURCES: Record<
  string,
  { dwSourceType: string; requiredTable: string; recordKind: SourceType }
> = Object.fromEntries(
  EXTERNAL_INBOX_SOURCES.map((s) => [
    s.product,
    {
      dwSourceType: s.dwSourceType,
      requiredTable: s.requiredTables[0],
      recordKind: s.recordKind,
    },
  ]),
);

const ALL_SOURCE_PRODUCTS: SourceKey[] = [
  "conversations",
  "error_tracking",
  "health_checks",
  "session_replay",
  ...EXTERNAL_INBOX_SOURCES.map((s) => s.product),
];

function isSetupSourceProduct(product: SourceKey): boolean {
  return product in DATA_WAREHOUSE_SOURCES;
}

function computeValues(
  configs: SignalSourceConfig[] | undefined,
): SignalSourceValues {
  const result = Object.fromEntries(
    ALL_SOURCE_PRODUCTS.map((p) => [p, false]),
  ) as SignalSourceValues;
  if (!configs?.length) return result;
  for (const product of ALL_SOURCE_PRODUCTS) {
    if (product === "error_tracking") {
      result.error_tracking = ERROR_TRACKING_SOURCE_TYPES.every((st) =>
        configs.some(
          (c) =>
            c.source_product === "error_tracking" &&
            c.source_type === st &&
            c.enabled,
        ),
      );
    } else {
      result[product] = configs.some(
        (c) => c.source_product === product && c.enabled,
      );
    }
  }
  return result;
}

/**
 * Source-product toggle state and behavior for the Self-driving sources UI.
 *
 * Owns:
 *  - Reading `signal_source_configs` + connected DWH sources to derive enabled/required-setup state.
 *  - Optimistic per-source toggle overrides so a click reflects without waiting for the API.
 *  - Triggering the warehouse setup wizard when a source requires it (`github`, `linear`, `zendesk`, `pganalyze`).
 *  - Forcing `issues` (`should_sync=true`, `sync_type=full_refresh` for GitHub/Linear) when a source is turned on.
 */
export function useSignalSourceToggles() {
  const client = useAuthenticatedClient();
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const queryClient = useQueryClient();
  const { data: configs, isLoading: configsLoading } = useSignalSourceConfigs();
  const { data: externalSources, isLoading: sourcesLoading } =
    useExternalDataSources();

  // Optimistic overrides keyed by source product – only sources actively being
  // toggled get an entry, so unrelated sources never see a prop change.
  const [optimistic, setOptimistic] = useState<
    Partial<Record<keyof SignalSourceValues, boolean>>
  >({});
  const pendingRef = useRef(new Set<keyof SignalSourceValues>());

  const [setupSource, setSetupSource] = useState<SourceKey | null>(null);
  const [loadingSources, setLoadingSources] = useState<
    Partial<Record<keyof SignalSourceValues, boolean>>
  >({});

  const isLoading = configsLoading || sourcesLoading;

  const findExternalSource = useCallback(
    (product: string) => {
      const dwConfig = DATA_WAREHOUSE_SOURCES[product];
      if (!dwConfig || !externalSources) return null;
      return externalSources.find(
        (s) =>
          s.source_type.toLowerCase() === dwConfig.dwSourceType.toLowerCase(),
      );
    },
    [externalSources],
  );

  const serverValues = useMemo<SignalSourceValues>(
    () => computeValues(configs),
    [configs],
  );

  // Optimistic overrides take precedence over server values.
  const displayValues = useMemo<SignalSourceValues>(() => {
    if (Object.keys(optimistic).length === 0) return serverValues;
    return { ...serverValues, ...optimistic };
  }, [serverValues, optimistic]);

  const sourceStates = useMemo(() => {
    const states: Partial<
      Record<
        keyof SignalSourceValues,
        {
          requiresSetup: boolean;
          loading: boolean;
          syncStatus?: SignalSourceConfig["status"];
        }
      >
    > = {};
    for (const product of ALL_SOURCE_PRODUCTS) {
      const config = configs?.find((c) => c.source_product === product);
      if (isSetupSourceProduct(product)) {
        const hasExternalSource = !!findExternalSource(product);
        const isEnabled = serverValues[product];
        states[product] = {
          requiresSetup: !hasExternalSource && !isEnabled,
          loading: !!loadingSources[product],
          syncStatus: config?.status ?? null,
        };
      } else {
        states[product] = {
          requiresSetup: false,
          loading: false,
          syncStatus: config?.status ?? null,
        };
      }
    }
    return states;
  }, [findExternalSource, serverValues, loadingSources, configs]);

  const ensureRequiredTableSyncing = useCallback(
    async (product: string) => {
      if (!projectId || !client) return;
      const dwConfig = DATA_WAREHOUSE_SOURCES[product];
      if (!dwConfig) return;

      const source = findExternalSource(product);
      if (!source?.schemas || !Array.isArray(source.schemas)) return;

      const requiredSchema = source.schemas.find(
        (s) => s.name.toLowerCase() === dwConfig.requiredTable,
      );
      if (!requiredSchema) return;

      // Issue-like records (issues, findings, feedback, reviews) get edited/closed after
      // creation, so incremental append would miss updates — force a full refresh. Tickets
      // are treated as append-only (matches the original Zendesk behavior).
      if (sourceNeedsFullRefresh(dwConfig.recordKind as SignalRecordKind)) {
        const syncType = requiredSchema.sync_type;
        const needsUpdate =
          !requiredSchema.should_sync || syncType !== "full_refresh";

        if (needsUpdate) {
          await client.updateExternalDataSchema(projectId, requiredSchema.id, {
            should_sync: true,
            sync_type: "full_refresh",
          });
        }
        return;
      }

      if (!requiredSchema.should_sync) {
        await client.updateExternalDataSchema(projectId, requiredSchema.id, {
          should_sync: true,
        });
      }
    },
    [projectId, client, findExternalSource],
  );

  const handleSetup = useCallback((source: keyof SignalSourceValues) => {
    if (isSetupSourceProduct(source)) {
      setSetupSource(source);
    }
  }, []);

  const invalidateAfterToggle = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: ["signals", "source-configs"],
      }),
      queryClient.invalidateQueries({
        queryKey: ["inbox", "signal-reports"],
      }),
    ]);
  }, [queryClient]);

  /**
   * Toggle a single source product. Calls the API directly (no react-query
   * mutation tracking) so intermediate loading/success states don't cause
   * cascading re-renders.
   */
  const handleToggle = useCallback(
    async (product: keyof SignalSourceValues, enabled: boolean) => {
      if (!client || !projectId) return;
      if (pendingRef.current.has(product)) return;

      // Warehouse sources without a connected external data source need setup first.
      if (enabled && isSetupSourceProduct(product)) {
        const hasExternalSource = !!findExternalSource(product);
        if (!hasExternalSource) {
          setSetupSource(product);
          return;
        }

        setLoadingSources((prev) => ({ ...prev, [product]: true }));
        try {
          await ensureRequiredTableSyncing(product);
        } finally {
          setLoadingSources((prev) => ({ ...prev, [product]: false }));
        }
      }

      pendingRef.current.add(product);
      setOptimistic((prev) => ({ ...prev, [product]: enabled }));

      const label = SOURCE_LABELS[product];
      const hadExistingConfig = configs?.some(
        (c) => c.source_product === product,
      );
      try {
        if (product === "error_tracking") {
          for (const sourceType of ERROR_TRACKING_SOURCE_TYPES) {
            const existing = configs?.find(
              (c) =>
                c.source_product === "error_tracking" &&
                c.source_type === sourceType,
            );
            if (existing) {
              await client.updateSignalSourceConfig(projectId, existing.id, {
                enabled,
              });
            } else if (enabled) {
              await client.createSignalSourceConfig(projectId, {
                source_product: "error_tracking",
                source_type: sourceType,
                enabled: true,
              });
            }
          }
        } else {
          const existing = configs?.find((c) => c.source_product === product);
          const sourceType = SOURCE_TYPE_MAP[product];
          if (existing) {
            await client.updateSignalSourceConfig(projectId, existing.id, {
              enabled,
            });
          } else if (enabled && sourceType) {
            await client.createSignalSourceConfig(projectId, {
              source_product: product,
              source_type: sourceType,
              enabled: true,
            });
          }
        }

        if (enabled) {
          track(ANALYTICS_EVENTS.SIGNAL_SOURCE_CONNECTED, {
            source_product: product,
            is_first_connection: !hadExistingConfig,
            via_setup_wizard: false,
          });
        }

        await invalidateAfterToggle();
      } catch (error: unknown) {
        const message =
          error instanceof Error ? error.message : `Failed to toggle ${label}`;
        toast.error(message);
      } finally {
        pendingRef.current.delete(product);
        setOptimistic((prev) => {
          const next = { ...prev };
          delete next[product];
          return next;
        });
      }
    },
    [
      client,
      projectId,
      configs,
      findExternalSource,
      ensureRequiredTableSyncing,
      invalidateAfterToggle,
    ],
  );

  const handleSetupComplete = useCallback(async () => {
    const completedSource = setupSource;
    setSetupSource(null);

    if (completedSource && client && projectId) {
      const existing = configs?.find(
        (c) => c.source_product === completedSource,
      );
      const sourceType = SOURCE_TYPE_MAP[completedSource];
      try {
        if (!existing && sourceType) {
          await client.createSignalSourceConfig(projectId, {
            source_product: completedSource,
            source_type: sourceType,
            enabled: true,
          });
        } else if (existing && !existing.enabled) {
          await client.updateSignalSourceConfig(projectId, existing.id, {
            enabled: true,
          });
        }
        track(ANALYTICS_EVENTS.SIGNAL_SOURCE_CONNECTED, {
          source_product: completedSource,
          is_first_connection: !existing,
          via_setup_wizard: true,
        });
      } catch {
        toast.error(
          "Data source connected, but failed to enable the Self-driving input. Try toggling it on.",
        );
      }
    }

    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["external-data-sources"] }),
      queryClient.invalidateQueries({
        queryKey: ["signals", "source-configs"],
      }),
      queryClient.invalidateQueries({
        queryKey: ["inbox", "signal-reports"],
      }),
    ]);
  }, [queryClient, setupSource, configs, client, projectId]);

  const handleSetupCancel = useCallback(() => {
    setSetupSource(null);
  }, []);

  return {
    displayValues,
    sourceStates,
    setupSource,
    isLoading,
    handleToggle,
    handleSetup,
    handleSetupComplete,
    handleSetupCancel,
  };
}
