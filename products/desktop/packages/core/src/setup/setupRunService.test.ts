import type {
  ISetupRunService,
  ISetupStore,
} from "@posthog/core/setup/identifiers";
import { SetupRunService } from "@posthog/core/setup/setupRunService";
import type {
  ActivityEntry,
  EnricherStatus,
} from "@posthog/core/setup/setupState";
import type { DiscoveredTask } from "@posthog/core/setup/types";
import type { RootLogger } from "@posthog/di/logger";
import { beforeEach, describe, expect, it, vi } from "vitest";

const REPO = "/repo/a";

function flush(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

const noopLogger: RootLogger = {
  info: () => {},
  warn: () => {},
  error: () => {},
  debug: () => {},
  scope: () => noopLogger,
};

interface FakeStore extends ISetupStore {
  discoveredTasks: DiscoveredTask[];
  enricherStatus: Map<string, EnricherStatus>;
  discoveryStarted: boolean;
}

function makeStore(
  initialEnricher: Record<string, EnricherStatus> = {},
): FakeStore {
  const enricherStatus = new Map<string, EnricherStatus>(
    Object.entries(initialEnricher),
  );
  const discoveredTasks: DiscoveredTask[] = [];
  return {
    discoveredTasks,
    enricherStatus,
    discoveryStarted: false,
    getDiscoveryStatus: () => "idle",
    getEnricherStatus: (repoPath) => enricherStatus.get(repoPath) ?? "idle",
    anyDiscoveryStarted() {
      return this.discoveryStarted;
    },
    startDiscovery() {
      this.discoveryStarted = true;
    },
    completeDiscovery() {},
    failDiscovery() {},
    pushDiscoveryActivity(_repoPath: string, _entry: ActivityEntry) {},
    startEnrichment(repoPath) {
      enricherStatus.set(repoPath, "running");
    },
    completeEnrichment(repoPath) {
      enricherStatus.set(repoPath, "done");
    },
    failEnrichment(repoPath) {
      enricherStatus.set(repoPath, "error");
    },
    addEnricherSuggestionIfMissing(task) {
      if (
        discoveredTasks.some(
          (t) => t.id === task.id && t.repoPath === task.repoPath,
        )
      ) {
        return;
      }
      discoveredTasks.push({ ...task, source: "enricher" });
    },
  };
}

function makePort(overrides: Partial<ISetupRunService> = {}): ISetupRunService {
  return {
    getDiscoveryContext: vi.fn(async () => ({
      apiHost: null,
      projectId: null,
      authed: false,
    })),
    createDiscoveryTask: vi.fn(async () => ({ id: "task-1" })),
    createTaskRun: vi.fn(async () => ({ id: "run-1" })),
    getTaskRun: vi.fn(async () => ({ status: "in_progress", tasks: null })),
    isTerminalStatus: vi.fn(() => false),
    startAgent: vi.fn(async () => {}),
    sendPrompt: vi.fn(async () => {}),
    subscribeSessionEvents: vi.fn(() => ({ unsubscribe: () => {} })),
    detectPosthogInstallState: vi.fn(async () => "not_installed" as const),
    findStaleFlagSuggestions: vi.fn(async () => []),
    includeExperiments: vi.fn(() => false),
    trackDiscoveryStarted: vi.fn(),
    trackDiscoveryCompleted: vi.fn(),
    trackDiscoveryFailed: vi.fn(),
    reportError: vi.fn(),
    ...overrides,
  };
}

let store: FakeStore;

beforeEach(() => {
  store = makeStore();
});

describe("SetupRunService enricher", () => {
  it("adds the sdk-health suggestion + stale flags when PostHog is initialized", async () => {
    const port = makePort({
      detectPosthogInstallState: vi.fn(async () => "initialized" as const),
      findStaleFlagSuggestions: vi.fn(async () => [
        {
          flagKey: "old-flag",
          referenceCount: 1,
          references: [{ file: "a.ts", line: 1, method: "isFeatureEnabled" }],
        },
      ]),
    });
    const service = new SetupRunService(port, store, noopLogger);

    service.startEnricherForRepo(REPO);
    await flush();

    const ids = store.discoveredTasks.map((t) => t.id);
    expect(ids).toContain("posthog-sdk-health");
    expect(ids).toContain("posthog-stale-flag-old-flag");
    expect(store.getEnricherStatus(REPO)).toBe("done");
  });

  it("adds the posthog-setup suggestion when PostHog is not installed", async () => {
    const port = makePort({
      detectPosthogInstallState: vi.fn(async () => "not_installed" as const),
    });
    const service = new SetupRunService(port, store, noopLogger);

    service.startEnricherForRepo(REPO);
    await flush();

    const ids = store.discoveredTasks.map((t) => t.id);
    expect(ids).toContain("posthog-setup");
    expect(port.findStaleFlagSuggestions).not.toHaveBeenCalled();
    expect(store.getEnricherStatus(REPO)).toBe("done");
  });

  it("marks enrichment failed when install-state detection throws", async () => {
    const port = makePort({
      detectPosthogInstallState: vi.fn(async () => {
        throw new Error("boom");
      }),
    });
    const service = new SetupRunService(port, store, noopLogger);

    service.startEnricherForRepo(REPO);
    await flush();

    expect(store.getEnricherStatus(REPO)).toBe("error");
  });

  it("does not re-run enrichment once a repo is done", async () => {
    store = makeStore({ [REPO]: "done" });
    const port = makePort();
    const service = new SetupRunService(port, store, noopLogger);

    service.startEnricherForRepo(REPO);
    await flush();

    expect(port.detectPosthogInstallState).not.toHaveBeenCalled();
  });
});

describe("SetupRunService discovery gating", () => {
  it("launches discovery at most once across repos", async () => {
    const port = makePort();
    const service = new SetupRunService(port, store, noopLogger);

    service.startDiscovery(REPO);
    service.startDiscovery("/repo/b");
    await flush();

    expect(port.getDiscoveryContext).toHaveBeenCalledTimes(1);
  });

  it("fails fast with missing_auth when no apiHost/projectId", async () => {
    const port = makePort({
      getDiscoveryContext: vi.fn(async () => ({
        apiHost: null,
        projectId: null,
        authed: false,
      })),
    });
    const service = new SetupRunService(port, store, noopLogger);

    service.startDiscovery(REPO);
    await flush();

    expect(port.trackDiscoveryFailed).toHaveBeenCalledWith(
      expect.objectContaining({
        reason: "startup_error",
        errorMessage: "missing_auth",
      }),
    );
    expect(port.startAgent).not.toHaveBeenCalled();
  });
});
