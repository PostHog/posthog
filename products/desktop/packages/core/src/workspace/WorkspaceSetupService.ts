import {
  ROOT_LOGGER,
  type RootLogger,
  type ScopedLogger,
} from "@posthog/di/logger";
import { inject, injectable } from "inversify";
import {
  WORKSPACE_SETUP_GIT_CLIENT,
  type WorkspaceSetupGitClient,
} from "./identifiers";
import { detectRepoFullName, isRepoMismatch } from "./repoMismatch";

export type FolderSelectionEvaluation =
  | { kind: "mismatch"; detectedRepo: string }
  | { kind: "proceed" };

@injectable()
export class WorkspaceSetupService {
  private readonly log: ScopedLogger;

  constructor(
    @inject(WORKSPACE_SETUP_GIT_CLIENT)
    private readonly git: WorkspaceSetupGitClient,
    @inject(ROOT_LOGGER)
    rootLogger: RootLogger,
  ) {
    this.log = rootLogger.scope("workspace-setup-service");
  }

  public async evaluateFolderSelection(
    repository: string | null,
    path: string,
  ): Promise<FolderSelectionEvaluation> {
    if (!repository) {
      return { kind: "proceed" };
    }

    let detected: Awaited<ReturnType<WorkspaceSetupGitClient["detectRepo"]>> =
      null;
    try {
      detected = await this.git.detectRepo({ directoryPath: path });
    } catch (error) {
      this.log.warn("Failed to detect repo for mismatch check", {
        error,
        path,
      });
      return { kind: "proceed" };
    }

    const detectedFullName = detectRepoFullName(detected);
    if (detectedFullName && isRepoMismatch(repository, detectedFullName)) {
      return { kind: "mismatch", detectedRepo: detectedFullName };
    }

    return { kind: "proceed" };
  }
}
