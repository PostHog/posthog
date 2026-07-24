import {
  ROOT_LOGGER,
  type RootLogger,
  type ScopedLogger,
} from "@posthog/di/logger";
import { TypedEventEmitter } from "@posthog/shared";
import { inject, injectable } from "inversify";
import type { GitPrService } from "../git-pr/git-pr";
import type { CreatePrHost } from "../git-pr/identifiers";
import { GIT_PR_SERVICE } from "../git-pr/identifiers";
import {
  GitServiceEvent,
  type GitServiceEvents,
  type GitWorkspaceLookup,
  type HostGitAgentService,
  type HostGitWorkspaceClient,
} from "./host-git";
import {
  GIT_AGENT_SERVICE,
  GIT_WORKSPACE_CLIENT,
  GIT_WORKSPACE_LOOKUP,
} from "./identifiers";
import type {
  CreatePrInput,
  CreatePrOutput,
  GitStateSnapshot,
} from "./router-schemas";

@injectable()
export class GitHostService extends TypedEventEmitter<GitServiceEvents> {
  private readonly log: ScopedLogger;

  constructor(
    @inject(GIT_WORKSPACE_CLIENT)
    private readonly workspaceClient: HostGitWorkspaceClient,
    @inject(GIT_PR_SERVICE)
    private readonly gitPrService: GitPrService,
    @inject(GIT_AGENT_SERVICE)
    private readonly agentService: HostGitAgentService,
    @inject(GIT_WORKSPACE_LOOKUP)
    private readonly workspaceLookup: GitWorkspaceLookup,
    @inject(ROOT_LOGGER)
    logger: RootLogger,
  ) {
    super();
    this.log = logger.scope("git-host");
  }

  private get git() {
    return this.workspaceClient.git;
  }

  async cloneRepository(
    repoUrl: string,
    targetPath: string,
    cloneId: string,
  ): Promise<{ cloneId: string }> {
    const subscription = this.git.onCloneProgress.subscribe(undefined, {
      onData: (payload) => {
        if (payload.cloneId === cloneId) {
          this.emit(GitServiceEvent.CloneProgress, payload);
        }
      },
      onError: (err) =>
        this.log.warn("clone progress subscription error", { err }),
    });
    try {
      return await this.git.cloneRepository.mutate({
        repoUrl,
        targetPath,
        cloneId,
      });
    } finally {
      subscription.unsubscribe();
    }
  }

  async createPr(input: CreatePrInput): Promise<CreatePrOutput> {
    const flowId = input.flowId;
    const result = await this.gitPrService.createPr(
      {
        directoryPath: input.directoryPath,
        branchName: input.branchName,
        commitMessage: input.commitMessage,
        prTitle: input.prTitle,
        prBody: input.prBody,
        draft: input.draft,
        stagedOnly: input.stagedOnly,
        taskId: input.taskId,
        conversationContext: input.conversationContext,
      },
      this.buildCreatePrHost(),
      (step, message, prUrl) => {
        this.emit(GitServiceEvent.CreatePrProgress, {
          flowId,
          step,
          message,
          prUrl,
        });
      },
    );

    return {
      success: result.success,
      message: result.message,
      prUrl: result.prUrl,
      failedStep: result.failedStep as CreatePrOutput["failedStep"],
      state: result.state as GitStateSnapshot | undefined,
    };
  }

  private async getSessionEnv(
    taskId: string | undefined,
  ): Promise<Record<string, string> | undefined> {
    if (!taskId) return undefined;
    try {
      const env = await this.agentService.getSessionEnvForTask(taskId);
      return Object.keys(env).length > 0 ? env : undefined;
    } catch (err) {
      this.log.warn("Failed to load session env for task", { taskId, err });
      return undefined;
    }
  }

  private async getPrStateSnapshot(
    directoryPath: string,
  ): Promise<GitStateSnapshot> {
    const [changedFiles, diffStats, syncStatus, latestCommit, prStatus] =
      await Promise.allSettled([
        this.git.getChangedFilesHead.query({ directoryPath }),
        this.git.getDiffStats.query({ directoryPath }),
        this.git.getGitSyncStatus.query({
          directoryPath,
          fetchFromRemote: true,
        }),
        this.git.getLatestCommit.query({ directoryPath }),
        this.git.getPrStatus.query({ directoryPath }),
      ]);
    const ok = <T>(r: PromiseSettledResult<T>): T | undefined =>
      r.status === "fulfilled" ? r.value : undefined;
    return {
      changedFiles: ok(changedFiles),
      diffStats: ok(diffStats),
      syncStatus: ok(syncStatus),
      latestCommit: ok(latestCommit) ?? undefined,
      prStatus: ok(prStatus),
    };
  }

  private buildCreatePrHost(): CreatePrHost {
    const git = this.git;
    return {
      getSessionEnvForTask: (taskId) => this.getSessionEnv(taskId),
      getCurrentBranch: (dir) =>
        git.getCurrentBranch.query({ directoryPath: dir }),
      createBranch: async (dir, name) => {
        await git.createBranch.mutate({ directoryPath: dir, branchName: name });
      },
      getChangedFilesHead: (dir) =>
        git.getChangedFilesHead.query({ directoryPath: dir }),
      getHeadSha: (dir) => git.getHeadSha.query({ directoryPath: dir }),
      commit: (dir, message, options) =>
        git.commit.mutate({
          directoryPath: dir,
          message,
          stagedOnly: options.stagedOnly,
          env: options.env,
        }),
      resetSoft: async (dir, sha) => {
        await git.resetSoft.mutate({ directoryPath: dir, sha });
      },
      getSyncStatus: (dir) =>
        git.getGitSyncStatus.query({ directoryPath: dir }),
      push: (dir, env) =>
        git.push.mutate({ directoryPath: dir, remote: "origin", env }),
      publish: (dir, env) =>
        git.publish.mutate({ directoryPath: dir, remote: "origin", env }),
      createPrViaGh: (dir, title, body, draft, env) =>
        git.createPrViaGh.mutate({
          directoryPath: dir,
          title,
          body,
          draft,
          env,
        }),
      linkBranch: (taskId, branch, source) =>
        this.workspaceLookup.linkBranch(taskId, branch, source),
      getPrState: (dir) => this.getPrStateSnapshot(dir),
    };
  }
}
