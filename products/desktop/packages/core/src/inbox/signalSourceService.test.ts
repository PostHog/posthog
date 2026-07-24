import type {
  ExternalDataSource,
  PostHogAPIClient,
  SignalSourceConfig,
} from "@posthog/api-client/posthog-client";
import { describe, expect, it, vi } from "vitest";
import {
  computeSourceValues,
  deriveSourceStates,
  SignalSourceService,
} from "./signalSourceService";

function config(
  product: SignalSourceConfig["source_product"],
  sourceType: SignalSourceConfig["source_type"],
  enabled: boolean,
): SignalSourceConfig {
  return {
    id: `${product}-${sourceType}`,
    source_product: product,
    source_type: sourceType,
    enabled,
    config: {},
    created_at: "",
    updated_at: "",
    status: null,
  };
}

function fakeClient(overrides: Partial<PostHogAPIClient> = {}) {
  return {
    createSignalSourceConfig: vi.fn().mockResolvedValue({}),
    updateSignalSourceConfig: vi.fn().mockResolvedValue({}),
    updateExternalDataSchema: vi.fn().mockResolvedValue({}),
    updateEvaluation: vi.fn().mockResolvedValue({}),
    updateSignalTeamConfig: vi.fn().mockResolvedValue({}),
    updateSignalUserAutonomyConfig: vi.fn().mockResolvedValue({}),
    deleteSignalUserAutonomyConfig: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  } as unknown as PostHogAPIClient;
}

describe("computeSourceValues", () => {
  it("requires all three error_tracking source types enabled", () => {
    const partial = computeSourceValues([
      config("error_tracking", "issue_created", true),
      config("error_tracking", "issue_reopened", true),
    ]);
    expect(partial.error_tracking).toBe(false);

    const full = computeSourceValues([
      config("error_tracking", "issue_created", true),
      config("error_tracking", "issue_reopened", true),
      config("error_tracking", "issue_spiking", true),
    ]);
    expect(full.error_tracking).toBe(true);
  });

  it("enables a non-error source when any config is enabled", () => {
    const values = computeSourceValues([config("github", "issue", true)]);
    expect(values.github).toBe(true);
  });

  it("enables health_checks when its config is enabled", () => {
    const values = computeSourceValues([
      config("health_checks", "health_issue", true),
    ]);
    expect(values.health_checks).toBe(true);
  });
});

describe("deriveSourceStates", () => {
  it("flags a warehouse source needing setup when no external source is connected", () => {
    const states = deriveSourceStates([], []);
    expect(states.github?.requiresSetup).toBe(true);
    expect(states.error_tracking?.requiresSetup).toBe(false);
  });
});

describe("SignalSourceService.toggleSource", () => {
  it("returns requiresSetup for a warehouse source with no external data source", async () => {
    const service = new SignalSourceService();
    const result = await service.toggleSource(
      fakeClient(),
      1,
      "github",
      true,
      [],
      [],
    );
    expect(result.requiresSetup).toBe(true);
  });

  it("fans out error_tracking across the three source types", async () => {
    const client = fakeClient();
    const service = new SignalSourceService();
    await service.toggleSource(client, 1, "error_tracking", true, [], []);
    expect(client.createSignalSourceConfig).toHaveBeenCalledTimes(3);
  });

  it("reports first connection when no config existed", async () => {
    const client = fakeClient();
    const service = new SignalSourceService();
    const result = await service.toggleSource(
      client,
      1,
      "session_replay",
      true,
      [],
      [],
    );
    expect(result.isFirstConnection).toBe(true);
    expect(client.createSignalSourceConfig).toHaveBeenCalledTimes(1);
  });

  it("creates a health_checks config with the health_issue source type", async () => {
    const client = fakeClient();
    const service = new SignalSourceService();
    await service.toggleSource(client, 1, "health_checks", true, [], []);
    expect(client.createSignalSourceConfig).toHaveBeenCalledWith(1, {
      source_product: "health_checks",
      source_type: "health_issue",
      enabled: true,
    });
  });

  it("ensures the issues table syncs with full_refresh for github before enabling", async () => {
    const client = fakeClient();
    const service = new SignalSourceService();
    const external: ExternalDataSource[] = [
      {
        id: "ext1",
        source_type: "Github",
        status: "running",
        schemas: [
          { id: "s1", name: "issues", should_sync: false, sync_type: null },
        ],
      },
    ];
    await service.toggleSource(client, 1, "github", true, [], external);
    expect(client.updateExternalDataSchema).toHaveBeenCalledWith(1, "s1", {
      should_sync: true,
      sync_type: "full_refresh",
    });
  });
});

describe("SignalSourceService.buildSlackNotificationBody", () => {
  it("only writes passed keys translated to snake_case", () => {
    const service = new SignalSourceService();
    const body = service.buildSlackNotificationBody({ channel: "#alerts" });
    expect(body).toEqual({ slack_notification_channel: "#alerts" });
    expect("slack_notification_integration_id" in body).toBe(false);
  });
});
