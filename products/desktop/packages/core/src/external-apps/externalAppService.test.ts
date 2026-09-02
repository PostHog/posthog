import type { Workspace } from "@posthog/shared";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ExternalAppService } from "./externalAppService";
import type {
  ExternalAppsFocusCoordinator,
  ExternalAppsWorkspaceClient,
} from "./identifiers";

function makeClient(): {
  [K in keyof ExternalAppsWorkspaceClient]: ReturnType<typeof vi.fn>;
} {
  return {
    openInApp: vi.fn().mockResolvedValue({ success: true }),
    setLastUsed: vi.fn().mockResolvedValue(undefined),
    getDetectedApps: vi
      .fn()
      .mockResolvedValue([{ id: "vscode", name: "VS Code" }]),
    copyPath: vi.fn().mockResolvedValue(undefined),
  };
}

function makeFocus(): {
  [K in keyof ExternalAppsFocusCoordinator]: ReturnType<typeof vi.fn>;
} {
  return {
    getSession: vi.fn().mockReturnValue(null),
    enableFocus: vi.fn(),
  };
}

const worktreeWorkspace: Workspace = {
  mode: "worktree",
  branchName: "feature",
  worktreePath: "/wt/feature",
  folderPath: "/repo",
} as unknown as Workspace;

describe("ExternalAppService.openExternalApp", () => {
  let client: ReturnType<typeof makeClient>;
  let focus: ReturnType<typeof makeFocus>;
  let service: ExternalAppService;

  beforeEach(() => {
    client = makeClient();
    focus = makeFocus();
    service = new ExternalAppService(
      client as unknown as ExternalAppsWorkspaceClient,
      focus as unknown as ExternalAppsFocusCoordinator,
    );
  });

  it("opens the file, records last-used, and resolves the app name", async () => {
    const outcome = await service.openExternalApp(
      { type: "open-in-app", appId: "vscode" },
      "/repo/file.ts",
      "file.ts",
    );

    expect(client.openInApp).toHaveBeenCalledWith("vscode", "/repo/file.ts");
    expect(client.setLastUsed).toHaveBeenCalledWith("vscode");
    expect(outcome).toEqual({
      kind: "opened",
      appName: "VS Code",
      displayName: "file.ts",
      focus: undefined,
    });
  });

  it("returns open-failed without recording last-used when openInApp fails", async () => {
    client.openInApp.mockResolvedValue({ success: false, error: "no app" });

    const outcome = await service.openExternalApp(
      { type: "open-in-app", appId: "vscode" },
      "/repo/file.ts",
      "file.ts",
    );

    expect(client.setLastUsed).not.toHaveBeenCalled();
    expect(outcome).toEqual({ kind: "open-failed", error: "no app" });
  });

  it("copies the path for a copy-path action", async () => {
    const outcome = await service.openExternalApp(
      { type: "copy-path" },
      "/repo/file.ts",
      "file.ts",
    );

    expect(client.copyPath).toHaveBeenCalledWith("/repo/file.ts");
    expect(client.openInApp).not.toHaveBeenCalled();
    expect(outcome).toEqual({ kind: "copied", filePath: "/repo/file.ts" });
  });

  it("rebases the path onto the main repo when already focused", async () => {
    focus.getSession.mockReturnValue({ worktreePath: "/wt/feature" });

    await service.openExternalApp(
      { type: "open-in-app", appId: "vscode" },
      "/wt/feature/src/a.ts",
      "a.ts",
      { workspace: worktreeWorkspace, mainRepoPath: "/repo" },
    );

    expect(focus.enableFocus).not.toHaveBeenCalled();
    expect(client.openInApp).toHaveBeenCalledWith("vscode", "/repo/src/a.ts");
  });

  it("runs the focus saga as a precondition then rebases the path", async () => {
    focus.getSession.mockReturnValue(null);
    focus.enableFocus.mockResolvedValue({
      success: true,
      session: { mainStashRef: null },
      wasSwap: false,
    });

    const outcome = await service.openExternalApp(
      { type: "open-in-app", appId: "vscode" },
      "/wt/feature/src/a.ts",
      "a.ts",
      { workspace: worktreeWorkspace, mainRepoPath: "/repo" },
    );

    expect(focus.enableFocus).toHaveBeenCalledWith({
      mainRepoPath: "/repo",
      worktreePath: "/wt/feature",
      branch: "feature",
    });
    expect(client.openInApp).toHaveBeenCalledWith("vscode", "/repo/src/a.ts");
    expect(outcome).toMatchObject({
      kind: "opened",
      focus: { branchName: "feature" },
    });
  });

  it("returns focus-failed and does not open when the focus saga fails", async () => {
    focus.getSession.mockReturnValue(null);
    focus.enableFocus.mockResolvedValue({
      success: false,
      error: "dirty",
      session: null,
      wasSwap: false,
    });

    const outcome = await service.openExternalApp(
      { type: "open-in-app", appId: "vscode" },
      "/wt/feature/src/a.ts",
      "a.ts",
      { workspace: worktreeWorkspace, mainRepoPath: "/repo" },
    );

    expect(client.openInApp).not.toHaveBeenCalled();
    expect(outcome).toEqual({ kind: "focus-failed", error: "dirty" });
  });
});
