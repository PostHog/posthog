import {
  buildChannelContextBlock,
  buildChannelContextText,
  buildCustomInstructionsText,
  buildPromptBlocks,
} from "@posthog/core/editor/prompt-builder";
import type {
  ConnectParams,
  SessionService,
} from "@posthog/core/sessions/sessionService";
import {
  getTaskRepository,
  Saga,
  type SagaLogger,
  type TaskCreationInput,
  type TaskCreationOutput,
  type Workspace,
} from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { Task } from "@posthog/shared/domain-types";
import type { TaskCreationApiClient } from "./taskCreationApiClient";
import type {
  CloudPromptTransport,
  ImportedClaudeCliSession,
  ITaskCreationHost,
} from "./taskCreationHost";
import { resolveTaskRepository } from "./taskRepository";

export interface TaskCreationDeps {
  posthogClient: TaskCreationApiClient;
  host: ITaskCreationHost;
  sessionService: SessionService;
  onTaskReady?: (output: TaskCreationOutput) => void;
  track: (event: string, props?: Record<string, unknown>) => void;
}

interface WarmActivationPayload {
  transport: CloudPromptTransport;
  pendingUserMessage?: string;
  pendingUserArtifactIds?: string[];
  suppressWarmReuse: boolean;
  augmented: boolean;
}

// The local connect path appends channel CONTEXT.md to initialPrompt and gets
// the user's personalization via the workspace-server system prompt; cloud
// sends its first message as text and has no client-side system-prompt seam,
// so fold both blocks into the first message here. Order: user's message, then
// personalization (user-level), then channel context (workspace-level).
// Personalization is folded only when there is message text to augment.
function buildCloudFirstMessage(
  messageText: string | undefined,
  input: TaskCreationInput,
): { pendingUserMessage?: string; augmented: boolean } {
  const customInstructionsText = messageText
    ? buildCustomInstructionsText(input.customInstructions)
    : null;
  const channelContextText = buildChannelContextText(
    input.channelContext,
    input.channelName,
    input.channelContextId,
  );
  const pendingUserMessage =
    [messageText, customInstructionsText, channelContextText]
      .filter((part): part is string => !!part)
      .join("\n\n") || undefined;
  return {
    pendingUserMessage,
    augmented: !!(customInstructionsText || channelContextText),
  };
}

export class TaskCreationSaga extends Saga<
  TaskCreationInput,
  TaskCreationOutput
> {
  readonly sagaName = "TaskCreationSaga";

  constructor(
    private deps: TaskCreationDeps,
    logger?: SagaLogger,
  ) {
    super(logger);
  }

  protected async execute(
    input: TaskCreationInput,
  ): Promise<TaskCreationOutput> {
    const taskId = input.taskId;
    const folderPromise =
      !taskId && input.repoPath
        ? this.resolveFolder(input.repoPath)
        : undefined;

    const importedClaude = await this.importClaudeSession(input);

    const warmPayload =
      !taskId && input.workspaceMode === "cloud"
        ? await this.prepareWarmActivation(input)
        : null;

    let task = taskId
      ? await this.readOnlyStep("fetch_task", () =>
          this.deps.posthogClient.getTask(taskId),
        )
      : await this.createTask(input, warmPayload);

    // Session reconcile auto-recovers run-less local tasks; mark this one as
    // mid-creation so the recovery doesn't race the agent_session step below.
    this.deps.sessionService.markTaskCreationInFlight(task.id);

    if (importedClaude && input.repoPath) {
      await this.recordClaudeImport(input, importedClaude, task.id);
    }

    const repoKey = getTaskRepository(task);
    const repoPath =
      input.repoPath ??
      (await this.readOnlyStep("resolve_repo_path", () =>
        this.deps.host.getTaskDirectory(task.id, repoKey ?? undefined),
      ));

    const workspaceMode =
      input.workspaceMode ??
      (task.latest_run?.environment === "cloud" ? "cloud" : "local");

    let workspace: Workspace | null = null;
    const branch = input.branch ?? task.latest_run?.branch ?? null;
    const hasProvisioning =
      workspaceMode === "worktree" && !!repoPath && !input.taskId;

    if (hasProvisioning) {
      this.deps.host.setProvisioningActive(task.id);
      if (this.deps.onTaskReady) {
        this.deps.onTaskReady({ task, workspace });
      }
    }

    if (repoPath) {
      const folder = folderPromise
        ? await this.readOnlyStep("folder_registration", () => folderPromise)
        : await this.readOnlyStep("folder_registration", () =>
            this.resolveFolder(repoPath),
          );

      try {
        const workspaceInfo = await this.step({
          name: "workspace_creation",
          execute: async () => {
            return this.deps.host.createWorkspace({
              taskId: task.id,
              mainRepoPath: repoPath,
              folderId: folder.id,
              folderPath: repoPath,
              mode: workspaceMode,
              branch: branch ?? undefined,
              allowRemoteBranchCheckout: input.allowRemoteBranchCheckout,
              reuseExistingWorktree: input.reuseExistingWorktree,
            });
          },
          rollback: async () => {
            this.log.info("Rolling back: deleting workspace", {
              taskId: task.id,
            });
            await this.deps.host.deleteWorkspace({
              taskId: task.id,
              mainRepoPath: repoPath,
            });
          },
        });

        workspace = {
          taskId: task.id,
          folderId: folder.id,
          folderPath: repoPath,
          mode: workspaceMode,
          worktreePath: workspaceInfo.worktree?.worktreePath ?? null,
          worktreeName: workspaceInfo.worktree?.worktreeName ?? null,
          branchName: workspaceInfo.worktree?.branchName ?? null,
          baseBranch: workspaceInfo.worktree?.baseBranch ?? null,
          linkedBranch: workspaceInfo.linkedBranch ?? null,
          createdAt:
            workspaceInfo.worktree?.createdAt ?? new Date().toISOString(),
        };

        // Link after the workspace row exists, so the branch-mismatch prompt can
        // compare the session's branch against the live checkout.
        if (importedClaude) {
          this.linkImportedSessionBranch(input, task.id);
          workspace.linkedBranch =
            input.importedClaudeSession?.branch ?? workspace.linkedBranch;
        }
      } catch (error) {
        // For a fresh worktree task the prompt is already persisted as the task
        // description and the UI has navigated onto the task. Rolling the saga
        // back here would run task_creation's deleteTask and destroy that task,
        // losing the prompt. Instead keep the task with no workspace (the shape
        // openTask re-provisions from) so the user can retry setup on it.
        if (!hasProvisioning) throw error;
        const provisioningError =
          error instanceof Error ? error.message : String(error);
        this.log.error("Worktree provisioning failed; keeping task for retry", {
          taskId: task.id,
          error,
        });
        this.deps.host.clearProvisioning(task.id);
        // The in-flight mark is left to TTL-expire on purpose: this state has
        // its own retry-prompt UX, and auto-recovery would race the retry.
        return { task, workspace: null, provisioningError };
      }
    } else if (workspaceMode === "cloud") {
      await this.step({
        name: "cloud_workspace_creation",
        execute: async () => {
          return this.deps.host.createWorkspace({
            taskId: task.id,
            mainRepoPath: "",
            folderId: "",
            folderPath: "",
            mode: "cloud",
            branch: branch ?? undefined,
          });
        },
        rollback: async () => {
          this.log.info("Rolling back: deleting cloud workspace", {
            taskId: task.id,
          });
          await this.deps.host.deleteWorkspace({
            taskId: task.id,
            mainRepoPath: "",
          });
        },
      });

      workspace = {
        taskId: task.id,
        folderId: "",
        folderPath: "",
        mode: "cloud",
        worktreePath: null,
        worktreeName: null,
        branchName: null,
        baseBranch: branch,
        linkedBranch: null,
        createdAt: new Date().toISOString(),
      };
    }

    const extraDirectories = input.taskId
      ? []
      : (input.additionalDirectories ?? []).filter(
          (path) => path && path !== repoPath,
        );
    if (extraDirectories.length > 0) {
      await this.step({
        name: "additional_directories",
        execute: async () => {
          await Promise.all(
            extraDirectories.map((path) =>
              this.deps.host.addAdditionalDirectory({
                taskId: task.id,
                path,
              }),
            ),
          );
          return { taskId: task.id, paths: extraDirectories };
        },
        rollback: async ({ taskId, paths }) => {
          this.log.info("Rolling back: removing additional directories", {
            taskId,
          });
          await Promise.all(
            paths.map((path) =>
              this.deps.host
                .removeAdditionalDirectory({ taskId, path })
                .catch((error) => {
                  this.log.warn("Failed to remove additional directory", {
                    error,
                  });
                }),
            ),
          );
        },
      });
    }

    const shouldStartCloudRun = workspaceMode === "cloud" && !task.latest_run;

    // Warm-activated at create time: the backend already forwarded the first
    // message (with any uploaded artifacts) to the pre-warmed run.
    if (!taskId && warmPayload && task.latest_run) {
      if (warmPayload.augmented && warmPayload.pendingUserMessage) {
        this.deps.sessionService.rememberInitialCloudPrompt(
          task.id,
          warmPayload.pendingUserMessage,
        );
      }
      this.deps.track(ANALYTICS_EVENTS.PROMPT_SENT, {
        task_id: task.id,
        is_initial: true,
        execution_type: "cloud",
        prompt_length_chars: warmPayload.transport.messageText?.length ?? 0,
      });
    }

    // Channels "generic chat box": a repo-less local/worktree task still starts
    // an agent, in a per-task scratch dir. Provision it before signalling the
    // task is ready so the task view resolves the scratch dir as its cwd (a
    // synthetic local workspace) instead of showing the repo-picker prompt.
    let scratchCwd: string | null = null;
    if (
      !repoPath &&
      !input.taskId &&
      workspaceMode !== "cloud" &&
      input.allowNoRepo
    ) {
      scratchCwd = await this.readOnlyStep("scratch_dir", () =>
        this.deps.host.ensureScratchDir(task.id),
      );
    }

    if (!hasProvisioning && !shouldStartCloudRun && this.deps.onTaskReady) {
      this.deps.onTaskReady({ task, workspace });
    }

    if (hasProvisioning) {
      this.deps.host.clearProvisioning(task.id);
    }

    if (
      input.environmentId &&
      workspace?.worktreePath &&
      repoPath &&
      !input.taskId
    ) {
      this.dispatchEnvironmentSetup(
        task.id,
        input.environmentId,
        repoPath,
        workspace.worktreePath,
      );
    }

    if (shouldStartCloudRun) {
      task = await this.step({
        name: "cloud_run",
        execute: async () => {
          const prAuthorshipMode = input.cloudPrAuthorshipMode ?? "user";

          // Resolve a typed local-skill slash command (`/my-skill …`) into a
          // `<skill .../>` tag before building the transport, so the skill
          // bundle is collected and uploaded with the very first cloud message.
          // Without this a first-message `/my-skill` reaches the sandbox with no
          // bundle and is rejected as an unknown command (only a follow-up,
          // which already resolves, would work). prepareWarmActivation already
          // did this for fresh cloud creations; reuse its transport.
          const buildTransport =
            async (): Promise<CloudPromptTransport | null> => {
              if (
                !(input.content || input.filePaths?.length) ||
                workspaceMode !== "cloud"
              ) {
                return null;
              }
              const resolvedContent = input.content
                ? await this.deps.host.resolveLocalSkillCommandPrompt(
                    input.content,
                  )
                : "";
              return this.deps.host.getCloudPromptTransport(
                resolvedContent,
                input.filePaths,
              );
            };
          const transport = warmPayload
            ? warmPayload.transport
            : await buildTransport();

          const { pendingUserMessage, augmented } = warmPayload
            ? warmPayload
            : buildCloudFirstMessage(transport?.messageText, input);

          // The sandbox echoes pendingUserMessage back once it boots; until then
          // the optimistic placeholder would show the bare task description with
          // no CONTEXT.md / personalization chip. Hand the augmented message to
          // the session service so it seeds the placeholder right away.
          if (augmented && pendingUserMessage) {
            this.deps.sessionService.rememberInitialCloudPrompt(
              task.id,
              pendingUserMessage,
            );
          }
          // A cloud run always needs an explicit runtime adapter — the API rejects
          // `initial_permission_mode` unless `runtime_adapter` is set. Callers that don't pick one
          // (e.g. canvas generation) default to claude, matching the local-connect default below.
          const cloudAdapter = input.adapter ?? "claude";
          const taskRun = await this.deps.posthogClient.createTaskRun(task.id, {
            environment: "cloud",
            mode: "interactive",
            branch,
            adapter: cloudAdapter,
            model: input.model,
            reasoningLevel: input.reasoningLevel,
            sandboxEnvironmentId: input.sandboxEnvironmentId,
            customImageId: input.customImageId,
            prAuthorshipMode,
            autoPublish: input.cloudAutoPublish,
            rtkEnabled: input.cloudRtkEnabled,
            runSource: input.cloudRunSource ?? "manual",
            signalReportId: input.signalReportId,
            importedMcpServers: input.importedMcpServers,
            relayedMcpServers: input.relayedMcpServers,
            initialPermissionMode:
              input.executionMode ??
              (cloudAdapter === "codex" ? "auto" : "plan"),
          });
          if (!taskRun?.id) {
            throw new Error("Failed to create cloud run");
          }

          if (input.relayedMcpServers?.length) {
            // Best-effort: relay designation failing must not fail creation —
            // the run still works, minus desktop-relayed servers.
            await this.deps.sessionService
              .designateRelayedMcpServers(
                taskRun.id,
                input.relayedMcpServers.map((server) => server.name),
              )
              .catch(() => undefined);
          }

          const pendingUserArtifactIds = transport
            ? await this.deps.host.uploadRunAttachments(
                this.deps.posthogClient,
                task.id,
                taskRun.id,
                transport.filePaths,
                transport.skillBundles,
              )
            : [];

          const startedRun = await this.deps.posthogClient.startTaskRun(
            task.id,
            taskRun.id,
            {
              pendingUserMessage,
              pendingUserArtifactIds:
                pendingUserArtifactIds.length > 0
                  ? pendingUserArtifactIds
                  : undefined,
            },
          );

          if (transport) {
            this.deps.track(ANALYTICS_EVENTS.PROMPT_SENT, {
              task_id: task.id,
              is_initial: true,
              execution_type: "cloud",
              prompt_length_chars: transport.messageText?.length ?? 0,
            });
          }

          return startedRun;
        },
        rollback: async () => {
          this.log.info("Rolling back: cloud run (no-op)", {
            taskId: task.id,
          });
        },
      });

      if (!hasProvisioning && this.deps.onTaskReady) {
        this.deps.onTaskReady({ task, workspace });
      }
    }

    const isCloudCreate = !input.taskId && workspaceMode === "cloud";
    const agentCwd =
      workspace?.worktreePath ??
      workspace?.folderPath ??
      repoPath ??
      scratchCwd;

    const shouldConnect = !isCloudCreate && (!!input.taskId || !!agentCwd);

    if (shouldConnect) {
      const initialPrompt =
        !input.taskId && input.content
          ? await this.readOnlyStep("build_prompt_blocks", () =>
              buildPromptBlocks(
                input.content ?? "",
                input.filePaths ?? [],
                agentCwd ?? "",
              ),
            )
          : undefined;

      // Append the channel's CONTEXT.md as optional background, so tasks made
      // in a channel start with the shared context the agent would otherwise
      // have to rediscover. Kept after the user's prompt so the request leads.
      const channelContextBlock = buildChannelContextBlock(
        input.channelContext,
        input.channelName,
        input.channelContextId,
      );
      if (initialPrompt && channelContextBlock) {
        initialPrompt.push(channelContextBlock);
      }

      await this.step({
        name: "agent_session",
        execute: async () => {
          const connectParams: ConnectParams = {
            task,
            repoPath: agentCwd ?? "",
          };
          if (initialPrompt) connectParams.initialPrompt = initialPrompt;
          if (input.executionMode)
            connectParams.executionMode = input.executionMode;
          if (input.adapter) connectParams.adapter = input.adapter;
          if (input.model) connectParams.model = input.model;
          if (input.reasoningLevel)
            connectParams.reasoningLevel = input.reasoningLevel;
          if (importedClaude) {
            connectParams.importedSessionId = importedClaude.importedSessionId;
            connectParams.adapter = "claude";
          }

          this.deps.sessionService.connectToTask(connectParams);
          return { taskId: task.id };
        },
        rollback: async ({ taskId }) => {
          this.log.info("Rolling back: disconnecting agent session", {
            taskId,
          });
          await this.deps.sessionService.disconnectFromTask(taskId);
        },
      });
    }

    return { task, workspace };
  }

  /**
   * Snapshot an existing Claude Code CLI transcript into the app's Claude
   * config dir so the agent session can resume it. On rollback the copied
   * transcript is removed so abandoned snapshots don't accumulate.
   */
  private async importClaudeSession(
    input: TaskCreationInput,
  ): Promise<ImportedClaudeCliSession | undefined> {
    const repoPath = input.repoPath;
    if (
      input.taskId ||
      !input.importedClaudeSession ||
      !repoPath ||
      (input.workspaceMode ?? "local") !== "local"
    ) {
      return undefined;
    }
    const { sourceSessionId } = input.importedClaudeSession;
    return this.step({
      name: "import_claude_session",
      execute: () =>
        this.deps.host.importClaudeCliSession({ repoPath, sourceSessionId }),
      rollback: (imported) =>
        this.deps.host.deleteClaudeCliImport({
          repoPath,
          importedSessionId: imported.importedSessionId,
        }),
    });
  }

  /**
   * Link the task to the branch the CLI session worked on (best-effort, no
   * checkout). The standard branch-mismatch prompt then offers to switch if
   * the local checkout is elsewhere — consistent with how the app handles
   * sending a message on a differing branch.
   */
  private linkImportedSessionBranch(
    input: TaskCreationInput,
    taskId: string,
  ): void {
    const branchName = input.importedClaudeSession?.branch;
    if (!branchName) return;
    this.deps.host.linkTaskBranch({ taskId, branchName }).catch((error) => {
      this.log.warn("Failed to link imported session branch", { error });
    });
  }

  /**
   * Persist the import tracking row so the source session lists as `imported`
   * and reopens to this task. A first-class step paired with the import: on
   * rollback the row is dropped (by imported session id), so a later-step
   * failure can never leave a row pointing at a discarded task. Awaited so it
   * is ordered before any step that could trigger that rollback.
   */
  private async recordClaudeImport(
    input: TaskCreationInput,
    imported: ImportedClaudeCliSession,
    taskId: string,
  ): Promise<void> {
    const sourceSessionId = input.importedClaudeSession?.sourceSessionId;
    const repoPath = input.repoPath;
    if (!sourceSessionId || !repoPath) return;
    const { importedSessionId, fingerprint } = imported;
    await this.step({
      name: "record_claude_import",
      execute: () =>
        this.deps.host.recordClaudeCliImport({
          sourceSessionId,
          importedSessionId,
          repoPath,
          taskId,
          fingerprint,
        }),
      rollback: () =>
        this.deps.host.deleteClaudeCliImportRecord({ importedSessionId }),
    });
  }

  private async resolveFolder(repoPath: string) {
    const folders = await this.deps.host.getFolders();
    let existingFolder = folders.find((f) => f.path === repoPath);

    if (!existingFolder) {
      existingFolder = await this.deps.host.addFolder({ folderPath: repoPath });
    }
    return existingFolder;
  }

  private dispatchEnvironmentSetup(
    taskId: string,
    environmentId: string,
    repoPath: string,
    worktreePath: string,
  ): void {
    this.deps.host
      .getEnvironment({ repoPath, id: environmentId })
      .then((env) => {
        if (!env?.setup?.script) return;

        this.deps.host.dispatchSetupAction({
          taskId,
          command: env.setup.script,
          cwd: worktreePath,
          label: `Setup: ${env.name}`,
        });
      })
      .catch((error) => {
        this.log.error("Failed to dispatch environment setup script", {
          taskId,
          environmentId,
          error,
        });
      });
  }

  // Resolve the first message and pre-upload its attachments (skill bundles,
  // files) to the pre-warmed run before createTask, so the backend's warm
  // activation can forward them with the message. When attachments exist but
  // no warm lease is known, warm reuse is suppressed (branch omitted) and the
  // cold path uploads to the real run instead — a warm activation must never
  // deliver the first message without its attachments.
  private async prepareWarmActivation(
    input: TaskCreationInput,
  ): Promise<WarmActivationPayload | null> {
    if (!input.content && !input.filePaths?.length) {
      return null;
    }

    const resolvedContent = input.content
      ? await this.deps.host.resolveLocalSkillCommandPrompt(input.content)
      : "";
    const transport = this.deps.host.getCloudPromptTransport(
      resolvedContent,
      input.filePaths,
    );
    const { pendingUserMessage, augmented } = buildCloudFirstMessage(
      transport.messageText,
      input,
    );
    const base: WarmActivationPayload = {
      transport,
      pendingUserMessage,
      suppressWarmReuse: false,
      augmented,
    };

    const lease = input.repository
      ? this.deps.host.takeWarmTaskLease({
          repository: input.repository,
          branch: input.branch ?? null,
          runtimeAdapter: input.adapter ?? null,
          model: input.model ?? null,
          reasoningEffort: input.reasoningLevel ?? null,
          sandboxEnvironmentId: input.sandboxEnvironmentId ?? null,
          customImageId: input.customImageId ?? null,
        })
      : null;

    const requiresConfiguredWarm = Boolean(
      input.sandboxEnvironmentId || input.customImageId,
    );

    const needsAttachments =
      transport.filePaths.length > 0 || transport.skillBundles.length > 0;
    if (!needsAttachments) {
      return {
        ...base,
        suppressWarmReuse: requiresConfiguredWarm && !lease,
      };
    }
    if (!lease) {
      return { ...base, suppressWarmReuse: true };
    }

    try {
      const artifactIds = await this.deps.host.uploadRunAttachments(
        this.deps.posthogClient,
        lease.taskId,
        lease.runId,
        transport.filePaths,
        transport.skillBundles,
      );
      return {
        ...base,
        pendingUserArtifactIds:
          artifactIds.length > 0 ? artifactIds : undefined,
      };
    } catch (error) {
      this.log.warn(
        "Failed to upload attachments to warm run; falling back to cold creation",
        { taskId: lease.taskId, runId: lease.runId, error },
      );
      return { ...base, suppressWarmReuse: true };
    }
  }

  private async createTask(
    input: TaskCreationInput,
    warmPayload: WarmActivationPayload | null,
  ): Promise<Task> {
    const repository = await this.readOnlyStep("repo_detection", () =>
      resolveTaskRepository(input, this.deps.host, this.log),
    );

    return this.step({
      name: "task_creation",
      execute: async () => {
        const description = input.taskDescription ?? input.content ?? "";
        const result = await this.deps.posthogClient.createTask({
          description,
          repository: repository ?? undefined,
          github_integration:
            input.workspaceMode === "cloud" &&
            input.cloudRunSource === "signal_report"
              ? input.githubIntegrationId
              : undefined,
          github_user_integration:
            input.workspaceMode === "cloud" &&
            input.cloudRunSource !== "signal_report"
              ? input.githubUserIntegrationId
              : undefined,
          origin_product: input.signalReportId
            ? "signal_report"
            : "user_created",
          // The server associates the task with the report and records the implementation
          // task_run artefact — no relationship label is sent (associations are unlabelled).
          branch:
            input.workspaceMode === "cloud" && !warmPayload?.suppressWarmReuse
              ? (input.branch ?? null)
              : undefined,
          runtime_adapter:
            input.workspaceMode === "cloud"
              ? (input.adapter ?? null)
              : undefined,
          model:
            input.workspaceMode === "cloud" ? (input.model ?? null) : undefined,
          reasoning_effort:
            input.workspaceMode === "cloud"
              ? (input.reasoningLevel ?? null)
              : undefined,
          sandbox_environment_id:
            input.workspaceMode === "cloud" && !warmPayload?.suppressWarmReuse
              ? input.sandboxEnvironmentId
              : undefined,
          custom_image_id:
            input.workspaceMode === "cloud" && !warmPayload?.suppressWarmReuse
              ? input.customImageId
              : undefined,
          signal_report: input.signalReportId ?? undefined,
          channel: input.channelId ?? undefined,
          runtime: "acp",
          pending_user_message: warmPayload?.pendingUserMessage,
          pending_user_artifact_ids: warmPayload?.pendingUserArtifactIds,
          // If creation activates a pre-warmed run, this is the only request
          // that can carry the choice — the saga skips run creation entirely.
          auto_publish:
            input.workspaceMode === "cloud" && input.cloudAutoPublish
              ? true
              : undefined,
        });
        return result as unknown as Task;
      },
      rollback: async (createdTask) => {
        this.log.info("Rolling back: deleting task", {
          taskId: createdTask.id,
        });
        await this.deps.posthogClient.deleteTask(createdTask.id);
      },
    });
  }
}
