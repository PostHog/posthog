import {
  type ISetupRunService,
  type ISetupStore,
  SETUP_RUN_SERVICE,
  SETUP_STORE,
} from "@posthog/core/setup/identifiers";
import { buildDiscoveryPrompt } from "@posthog/core/setup/prompts";
import {
  handleSessionUpdate,
  nextActivityId,
} from "@posthog/core/setup/sessionUpdate";
import {
  buildPosthogSetupSuggestion,
  buildSdkHealthSuggestion,
  buildStaleFlagSuggestion,
} from "@posthog/core/setup/suggestions";
import {
  buildTaskDiscoverySchema,
  type DiscoveredTask,
} from "@posthog/core/setup/types";
import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import { inject, injectable } from "inversify";

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const onAbort = () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

@injectable()
export class SetupRunService {
  private anyDiscoveryEverLaunched = false;
  private discoveryStartingByRepo = new Set<string>();
  private enricherSuggestionsRunningByRepo = new Set<string>();

  constructor(
    @inject(SETUP_RUN_SERVICE)
    private readonly port: ISetupRunService,
    @inject(SETUP_STORE)
    private readonly store: ISetupStore,
    @inject(ROOT_LOGGER)
    private readonly logger: RootLogger,
  ) {}

  // Discovery is a one-time-per-user agent run; once any repo has triggered
  // it we never auto-launch another one. Errored/interrupted runs require
  // explicit user retry (see setupState partialize and #2257). Enricher runs
  // per repo on every selection (gated on per-repo status inside the service).
  maybeStart(directory: string, discoveryEnabled: boolean): void {
    if (!directory) return;

    this.startEnricherForRepo(directory);

    if (!discoveryEnabled) return;
    if (!this.store.anyDiscoveryStarted()) this.startDiscovery(directory);
  }

  startEnricherForRepo(directory: string): void {
    this.injectEnricherSuggestions(directory);
  }

  startDiscovery(directory: string): void {
    if (!directory) return;
    if (this.anyDiscoveryEverLaunched) return;
    if (this.discoveryStartingByRepo.has(directory)) return;
    const status = this.store.getDiscoveryStatus(directory);
    if (status === "running" || status === "done") return;
    this.anyDiscoveryEverLaunched = true;
    this.discoveryStartingByRepo.add(directory);
    this.runDiscovery(directory)
      .catch((err) => {
        this.logger.error("Discovery startup failed", { error: err });
      })
      .finally(() => {
        this.discoveryStartingByRepo.delete(directory);
      });
  }

  injectEnricherSuggestions(directory: string): void {
    if (!directory) return;
    if (this.enricherSuggestionsRunningByRepo.has(directory)) return;
    const enricherStatus = this.store.getEnricherStatus(directory);
    if (enricherStatus === "done" || enricherStatus === "running") return;
    this.enricherSuggestionsRunningByRepo.add(directory);
    this.store.startEnrichment(directory);
    this.runEnricher(directory).catch((err) => {
      this.logger.warn("Enricher run failed", { error: err });
    });
  }

  private async runEnricher(directory: string): Promise<void> {
    try {
      const installState = await this.port.detectPosthogInstallState(directory);

      if (installState === "initialized") {
        this.store.addEnricherSuggestionIfMissing({
          ...buildSdkHealthSuggestion(),
          repoPath: directory,
        });
        await this.injectStaleFlagSuggestions(directory);
      } else {
        const suggestion = buildPosthogSetupSuggestion(installState);
        this.store.addEnricherSuggestionIfMissing({
          ...suggestion,
          repoPath: directory,
        });
      }
      this.store.completeEnrichment(directory);
    } catch (err) {
      this.logger.warn("Enricher run failed", { error: err });
      this.store.failEnrichment(directory);
    } finally {
      this.enricherSuggestionsRunningByRepo.delete(directory);
    }
  }

  private async injectStaleFlagSuggestions(directory: string): Promise<void> {
    try {
      const flags = await this.port.findStaleFlagSuggestions(directory);
      for (const flag of flags) {
        this.store.addEnricherSuggestionIfMissing({
          ...buildStaleFlagSuggestion(flag),
          repoPath: directory,
        });
      }
    } catch (err) {
      this.logger.warn("Failed to find stale flag suggestions", { error: err });
    }
  }

  private async runDiscovery(directory: string): Promise<void> {
    const abort = new AbortController();
    const discoveryStartedAt = Date.now();

    try {
      const { apiHost, projectId, authed } =
        await this.port.getDiscoveryContext();
      if (abort.signal.aborted) return;

      if (!apiHost || !projectId) {
        this.logger.error("Missing auth for discovery", { apiHost, projectId });
        this.store.failDiscovery(directory, "Authentication required.");
        this.port.trackDiscoveryFailed({
          reason: "startup_error",
          errorMessage: "missing_auth",
        });
        return;
      }

      if (!authed) {
        this.store.failDiscovery(directory, "Authentication required.");
        this.port.trackDiscoveryFailed({
          reason: "startup_error",
          errorMessage: "unauthenticated_client",
        });
        return;
      }

      if (!directory) {
        this.store.failDiscovery(directory, "No directory selected.");
        this.port.trackDiscoveryFailed({
          reason: "startup_error",
          errorMessage: "missing_directory",
        });
        return;
      }

      const includeExperiments = this.port.includeExperiments();
      const discoveryPrompt = buildDiscoveryPrompt({ includeExperiments });
      const discoverySchema = buildTaskDiscoverySchema({ includeExperiments });

      const task = await this.port.createDiscoveryTask({
        title: "Discover first tasks",
        description: discoveryPrompt,
        jsonSchema: discoverySchema,
      });
      if (abort.signal.aborted) return;

      const taskRun = await this.port.createTaskRun(task.id);
      if (abort.signal.aborted) return;
      if (!taskRun?.id) {
        throw new Error("Failed to create discovery task run");
      }
      const taskRunId = taskRun.id;

      this.store.startDiscovery(directory, task.id, taskRunId);
      this.port.trackDiscoveryStarted({
        taskId: task.id,
        taskRunId,
      });

      await this.port.startAgent({
        taskId: task.id,
        taskRunId,
        repoPath: directory,
        apiHost,
        projectId,
        jsonSchema: discoverySchema,
      });
      if (abort.signal.aborted) return;

      this.port
        .sendPrompt({ sessionId: taskRunId, promptText: discoveryPrompt })
        .catch((err) => {
          this.logger.error("Failed to send discovery prompt", { error: err });
        });

      let completed = false;
      let subscription: { unsubscribe: () => void } | null = null;

      type CompletionSource =
        | "structured_output"
        | "terminal_status"
        | "missing_output";

      const finishSuccess = (
        tasks: DiscoveredTask[],
        signalSource: CompletionSource,
      ) => {
        if (completed || abort.signal.aborted) return;
        completed = true;
        subscription?.unsubscribe();

        const durationSeconds = Math.round(
          (Date.now() - discoveryStartedAt) / 1000,
        );

        this.logger.info("Discovery completed", {
          taskCount: tasks.length,
          signalSource,
        });
        this.store.completeDiscovery(directory, tasks);
        this.port.trackDiscoveryCompleted({
          taskId: task.id,
          taskRunId,
          taskCount: tasks.length,
          durationSeconds,
          signalSource,
        });
      };

      const finishFailure = (
        reason: "failed" | "cancelled" | "timeout",
        message: string,
      ) => {
        if (completed || abort.signal.aborted) return;
        completed = true;
        subscription?.unsubscribe();

        this.logger.error("Discovery failed", { reason });
        this.store.failDiscovery(directory, message);
        this.port.trackDiscoveryFailed({
          taskId: task.id,
          taskRunId,
          reason,
        });
      };

      let signalRetryStarted = false;
      const handleStructuredOutputSignal = async () => {
        if (signalRetryStarted) return;
        signalRetryStarted = true;
        const startedAt = Date.now();
        const TIMEOUT_MS = 8000;
        const MAX_DELAY_MS = 4000;
        let delay = 500;
        while (Date.now() - startedAt < TIMEOUT_MS) {
          try {
            await sleep(delay, abort.signal);
          } catch {
            return;
          }
          if (completed) return;
          try {
            const run = await this.port.getTaskRun(task.id, taskRunId);
            if (completed || abort.signal.aborted) return;
            if (run.tasks) {
              finishSuccess(run.tasks, "structured_output");
              return;
            }
          } catch (err) {
            this.logger.warn(
              "Failed to fetch run after StructuredOutput signal",
              {
                error: err,
              },
            );
          }
          delay = Math.min(delay * 2, MAX_DELAY_MS);
        }
      };

      let structuredOutputSeen = false;
      let wrapupBuffer = "";
      const WRAPUP_TOOL_CALL_ID = "discovery-wrapup";
      const pushWrapupActivity = (text: string) => {
        if (!structuredOutputSeen) return;
        wrapupBuffer = (wrapupBuffer + text).slice(-200);
        this.store.pushDiscoveryActivity(directory, {
          id: nextActivityId(),
          toolCallId: WRAPUP_TOOL_CALL_ID,
          tool: "WrappingUp",
          filePath: null,
          title: wrapupBuffer.trim(),
        });
      };

      subscription = this.port.subscribeSessionEvents(
        { taskRunId },
        {
          onData: (payload: unknown) => {
            handleSessionUpdate(
              payload,
              (entry) => {
                this.store.pushDiscoveryActivity(directory, entry);
                if (entry.tool === "StructuredOutput") {
                  structuredOutputSeen = true;
                  handleStructuredOutputSignal().catch((err) =>
                    this.logger.warn("StructuredOutput handler failed", {
                      error: err,
                    }),
                  );
                }
              },
              pushWrapupActivity,
            );
          },
          onError: (err) => {
            this.logger.error("Discovery subscription error", { error: err });
          },
        },
      );
      const subscriptionAtAbort = subscription;
      abort.signal.addEventListener(
        "abort",
        () => {
          subscriptionAtAbort.unsubscribe();
        },
        { once: true },
      );

      const pollForCompletion = async () => {
        const maxAttempts = 120;
        const intervalMs = 5000;

        for (let i = 0; i < maxAttempts; i++) {
          try {
            await sleep(intervalMs, abort.signal);
          } catch {
            return;
          }
          if (completed) return;

          try {
            const run = await this.port.getTaskRun(task.id, taskRunId);
            if (completed || abort.signal.aborted) return;

            if (this.port.isTerminalStatus(run.status)) {
              if (run.status === "completed" && run.tasks) {
                finishSuccess(run.tasks, "terminal_status");
              } else if (
                run.status === "failed" ||
                run.status === "cancelled"
              ) {
                finishFailure(
                  run.status,
                  "Discovery failed. You can skip or retry.",
                );
              } else {
                finishSuccess([], "missing_output");
              }
              return;
            }

            if (run.tasks) {
              finishSuccess(run.tasks, "missing_output");
              return;
            }
          } catch (err) {
            this.logger.warn("Failed to poll discovery", {
              attempt: i + 1,
              error: err,
            });
          }
        }

        finishFailure("timeout", "Discovery timed out. You can skip or retry.");
      };

      pollForCompletion().catch((err) => {
        if (abort.signal.aborted) return;
        this.logger.error("Discovery poll failed", { error: err });
        if (!completed) {
          completed = true;
          subscription?.unsubscribe();
          this.store.failDiscovery(directory, "Discovery failed unexpectedly.");
          this.port.trackDiscoveryFailed({
            taskId: task.id,
            taskRunId,
            reason: "failed",
            errorMessage:
              err instanceof Error ? err.message : "discovery_poll_error",
          });
          if (err instanceof Error) {
            this.port.reportError(err, "setup.discovery_poll");
          }
        }
      });
    } catch (err) {
      if (abort.signal.aborted) return;
      this.logger.error("Failed to start discovery", { error: err });
      const message =
        err instanceof Error ? err.message : "Failed to start discovery.";
      this.store.failDiscovery(directory, message);
      this.port.trackDiscoveryFailed({
        reason: "startup_error",
        errorMessage: message,
      });
      if (err instanceof Error) {
        this.port.reportError(err, "setup.start_discovery");
      }
    }
  }
}
