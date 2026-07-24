import type { Workspace } from "@posthog/shared";
import { inject, injectable } from "inversify";
import type { ExternalAppAction } from "../context-menu/schemas";
import type { FocusSagaResult } from "../focus/service";
import {
  EXTERNAL_APPS_FOCUS_COORDINATOR,
  EXTERNAL_APPS_WORKSPACE_CLIENT,
  type ExternalAppsFocusCoordinator,
  type ExternalAppsWorkspaceClient,
} from "./identifiers";

export interface ExternalAppWorkspaceContext {
  workspace: Workspace | null;
  mainRepoPath?: string;
}

export type ExternalAppActionOutcome =
  | {
      kind: "opened";
      appName: string;
      displayName: string;
      focus?: { branchName: string; result: FocusSagaResult };
    }
  | { kind: "open-failed"; error: string }
  | { kind: "focus-failed"; error: string }
  | { kind: "copied"; filePath: string };

interface EnsureFocusResult {
  effectivePath: string;
  focus?: { branchName: string; result: FocusSagaResult };
  blockingError?: string;
}

@injectable()
export class ExternalAppService {
  constructor(
    @inject(EXTERNAL_APPS_WORKSPACE_CLIENT)
    private readonly client: ExternalAppsWorkspaceClient,
    @inject(EXTERNAL_APPS_FOCUS_COORDINATOR)
    private readonly focus: ExternalAppsFocusCoordinator,
  ) {}

  async openExternalApp(
    action: ExternalAppAction,
    filePath: string,
    displayName: string,
    workspaceContext?: ExternalAppWorkspaceContext,
  ): Promise<ExternalAppActionOutcome> {
    if (action.type === "copy-path") {
      await this.client.copyPath(filePath);
      return { kind: "copied", filePath };
    }

    const focusResult = await this.ensureWorkspaceFocused(
      filePath,
      workspaceContext,
    );
    if (focusResult.blockingError) {
      return { kind: "focus-failed", error: focusResult.blockingError };
    }

    const openResult = await this.client.openInApp(
      action.appId,
      focusResult.effectivePath,
    );
    if (!openResult.success) {
      return {
        kind: "open-failed",
        error: openResult.error || "Unknown error",
      };
    }

    await this.client.setLastUsed(action.appId);
    const apps = await this.client.getDetectedApps();
    const app = apps.find((a) => a.id === action.appId);

    return {
      kind: "opened",
      appName: app?.name || "external app",
      displayName,
      focus: focusResult.focus,
    };
  }

  private async ensureWorkspaceFocused(
    filePath: string,
    workspaceContext?: ExternalAppWorkspaceContext,
  ): Promise<EnsureFocusResult> {
    const workspace = workspaceContext?.workspace;
    if (!workspace) {
      return { effectivePath: filePath };
    }

    const { mainRepoPath } = workspaceContext;
    if (
      workspace.mode !== "worktree" ||
      !workspace.branchName ||
      !workspace.worktreePath
    ) {
      return { effectivePath: filePath };
    }

    const session = this.focus.getSession();
    const isAlreadyFocused = session?.worktreePath === workspace.worktreePath;

    if (!mainRepoPath) {
      return { effectivePath: filePath };
    }

    if (isAlreadyFocused) {
      return {
        effectivePath: this.rebasePath(
          filePath,
          workspace.worktreePath,
          mainRepoPath,
        ),
      };
    }

    const result = await this.focus.enableFocus({
      mainRepoPath: workspace.folderPath,
      worktreePath: workspace.worktreePath,
      branch: workspace.branchName,
    });

    if (!result.success) {
      return { effectivePath: filePath, blockingError: result.error };
    }

    return {
      effectivePath: this.rebasePath(
        filePath,
        workspace.worktreePath,
        mainRepoPath,
      ),
      focus: { branchName: workspace.branchName, result },
    };
  }

  private rebasePath(
    filePath: string,
    worktreePath: string,
    mainRepoPath: string,
  ): string {
    const relativePath = filePath.replace(worktreePath, "");
    return `${mainRepoPath}${relativePath}`;
  }
}
