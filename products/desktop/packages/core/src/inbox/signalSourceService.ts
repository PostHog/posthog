import type {
  ExternalDataSource,
  ExternalDataSourceSchema,
  PostHogAPIClient,
  SignalSourceConfig,
} from "@posthog/api-client/posthog-client";
import {
  EXTERNAL_INBOX_SOURCES,
  type SignalRecordKind,
  sourceNeedsFullRefresh,
  type ToggleableSourceProduct,
} from "@posthog/shared";
import type { SignalUserAutonomyConfig } from "@posthog/shared/domain-types";
import { injectable } from "inversify";

export type SignalSourceProduct = ToggleableSourceProduct;
export type SignalSourceValues = Record<SignalSourceProduct, boolean>;
// Any warehouse source can be a setup target; membership in DATA_WAREHOUSE_SOURCES is the
// runtime narrowing, so this stays a broad alias rather than a hand-kept union.
export type WarehouseSourceProduct = SignalSourceProduct;

export interface SignalSourceState {
  requiresSetup: boolean;
  syncStatus: SignalSourceConfig["status"];
}

export interface ToggleSourceResult {
  requiresSetup: boolean;
  isFirstConnection: boolean;
}

type SourceType = SignalSourceConfig["source_type"];

// Non-warehouse toggles are hard-wired; warehouse sources are derived from the shared
// EXTERNAL_INBOX_SOURCES registry (kept in sync with the UI hook).
const SOURCE_TYPE_MAP: Partial<Record<SignalSourceProduct, SourceType>> = {
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

const ALL_SOURCE_PRODUCTS: SignalSourceProduct[] = [
  "conversations",
  "error_tracking",
  "health_checks",
  "session_replay",
  ...EXTERNAL_INBOX_SOURCES.map((s) => s.product),
];

function isWarehouseSource(product: SignalSourceProduct): boolean {
  return product in DATA_WAREHOUSE_SOURCES;
}

function findExternalSource(
  product: SignalSourceProduct,
  externalSources: ExternalDataSource[] | undefined,
): ExternalDataSource | null {
  if (!isWarehouseSource(product) || !externalSources) {
    return null;
  }
  const dwConfig = DATA_WAREHOUSE_SOURCES[product];
  return (
    externalSources.find(
      (s) =>
        s.source_type.toLowerCase() === dwConfig.dwSourceType.toLowerCase(),
    ) ?? null
  );
}

export function computeSourceValues(
  configs: SignalSourceConfig[] | undefined,
): SignalSourceValues {
  const result = Object.fromEntries(
    ALL_SOURCE_PRODUCTS.map((p) => [p, false]),
  ) as SignalSourceValues;
  if (!configs?.length) {
    return result;
  }
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

export function deriveSourceStates(
  configs: SignalSourceConfig[] | undefined,
  externalSources: ExternalDataSource[] | undefined,
): Partial<Record<SignalSourceProduct, SignalSourceState>> {
  const serverValues = computeSourceValues(configs);
  const states: Partial<Record<SignalSourceProduct, SignalSourceState>> = {};
  for (const product of ALL_SOURCE_PRODUCTS) {
    const config = configs?.find((c) => c.source_product === product);
    if (isWarehouseSource(product)) {
      states[product] = {
        requiresSetup:
          !findExternalSource(product, externalSources) &&
          !serverValues[product],
        syncStatus: config?.status ?? null,
      };
    } else {
      states[product] = {
        requiresSetup: false,
        syncStatus: config?.status ?? null,
      };
    }
  }
  return states;
}

function parseSchemas(
  source: ExternalDataSource | null,
): ExternalDataSourceSchema[] | null {
  if (!source?.schemas || !Array.isArray(source.schemas)) {
    return null;
  }
  return source.schemas;
}

@injectable()
export class SignalSourceService {
  private readonly pending = new Set<SignalSourceProduct>();

  isPending(product: SignalSourceProduct): boolean {
    return this.pending.has(product);
  }

  async ensureRequiredTableSyncing(
    client: PostHogAPIClient,
    projectId: number,
    product: WarehouseSourceProduct,
    externalSources: ExternalDataSource[] | undefined,
  ): Promise<void> {
    const dwConfig = DATA_WAREHOUSE_SOURCES[product];
    const schemas = parseSchemas(findExternalSource(product, externalSources));
    if (!schemas) {
      return;
    }

    const requiredSchema = schemas.find(
      (s) => s.name.toLowerCase() === dwConfig.requiredTable,
    );
    if (!requiredSchema) {
      return;
    }

    // Issue-like records (issues, findings, feedback, reviews) mutate after creation, so
    // they need full-refresh sync; tickets are append-only.
    if (sourceNeedsFullRefresh(dwConfig.recordKind as SignalRecordKind)) {
      const needsUpdate =
        !requiredSchema.should_sync ||
        requiredSchema.sync_type !== "full_refresh";
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
  }

  requiresSetup(
    product: SignalSourceProduct,
    externalSources: ExternalDataSource[] | undefined,
  ): boolean {
    return (
      isWarehouseSource(product) &&
      !findExternalSource(product, externalSources)
    );
  }

  async toggleSource(
    client: PostHogAPIClient,
    projectId: number,
    product: SignalSourceProduct,
    enabled: boolean,
    configs: SignalSourceConfig[] | undefined,
    externalSources: ExternalDataSource[] | undefined,
  ): Promise<ToggleSourceResult> {
    if (this.pending.has(product)) {
      return { requiresSetup: false, isFirstConnection: false };
    }

    if (
      enabled &&
      isWarehouseSource(product) &&
      this.requiresSetup(product, externalSources)
    ) {
      return { requiresSetup: true, isFirstConnection: false };
    }

    if (enabled && isWarehouseSource(product)) {
      await this.ensureRequiredTableSyncing(
        client,
        projectId,
        product,
        externalSources,
      );
    }

    const hadExistingConfig = !!configs?.some(
      (c) => c.source_product === product,
    );

    this.pending.add(product);
    try {
      if (product === "error_tracking") {
        await this.upsertErrorTracking(client, projectId, enabled, configs);
      } else {
        await this.upsertSingleSource(
          client,
          projectId,
          product,
          enabled,
          configs,
        );
      }
    } finally {
      this.pending.delete(product);
    }

    return { requiresSetup: false, isFirstConnection: !hadExistingConfig };
  }

  private async upsertErrorTracking(
    client: PostHogAPIClient,
    projectId: number,
    enabled: boolean,
    configs: SignalSourceConfig[] | undefined,
  ): Promise<void> {
    for (const sourceType of ERROR_TRACKING_SOURCE_TYPES) {
      const existing = configs?.find(
        (c) =>
          c.source_product === "error_tracking" && c.source_type === sourceType,
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
  }

  private async upsertSingleSource(
    client: PostHogAPIClient,
    projectId: number,
    product: Exclude<SignalSourceProduct, "error_tracking">,
    enabled: boolean,
    configs: SignalSourceConfig[] | undefined,
  ): Promise<void> {
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

  async completeSetup(
    client: PostHogAPIClient,
    projectId: number,
    product: WarehouseSourceProduct,
    configs: SignalSourceConfig[] | undefined,
  ): Promise<ToggleSourceResult> {
    const existing = configs?.find((c) => c.source_product === product);
    const sourceType = SOURCE_TYPE_MAP[product];
    if (!existing && sourceType) {
      await client.createSignalSourceConfig(projectId, {
        source_product: product,
        source_type: sourceType,
        enabled: true,
      });
    } else if (existing && !existing.enabled) {
      await client.updateSignalSourceConfig(projectId, existing.id, {
        enabled: true,
      });
    }
    return { requiresSetup: false, isFirstConnection: !existing };
  }

  async toggleEvaluation(
    client: PostHogAPIClient,
    projectId: number,
    evaluationId: string,
    enabled: boolean,
  ): Promise<void> {
    await client.updateEvaluation(projectId, evaluationId, { enabled });
  }

  async updateAutostartPriority(
    client: PostHogAPIClient,
    priority: string,
  ): Promise<void> {
    await client.updateSignalTeamConfig({
      default_autostart_priority: priority,
    });
  }

  buildSlackNotificationBody(updates: {
    integrationId?: number | null;
    channel?: string | null;
    minPriority?: string | null;
  }): Record<string, number | string | null> {
    const body: Record<string, number | string | null> = {};
    if ("integrationId" in updates) {
      body.slack_notification_integration_id = updates.integrationId ?? null;
    }
    if ("channel" in updates) {
      body.slack_notification_channel = updates.channel ?? null;
    }
    if ("minPriority" in updates) {
      body.slack_notification_min_priority = updates.minPriority ?? null;
    }
    return body;
  }

  async updateSlackNotifications(
    client: PostHogAPIClient,
    updates: {
      integrationId?: number | null;
      channel?: string | null;
      minPriority?: string | null;
    },
  ): Promise<SignalUserAutonomyConfig> {
    return client.updateSignalUserAutonomyConfig(
      this.buildSlackNotificationBody(updates),
    );
  }
}
