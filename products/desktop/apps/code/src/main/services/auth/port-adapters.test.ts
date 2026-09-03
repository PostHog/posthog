import type { WorkspaceClient } from "@posthog/workspace-client/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  WorkspaceServerEvent,
  WorkspaceServerService,
  WorkspaceServerStatus,
} from "../workspace-server/service";
import { ConnectivityPortAdapter } from "./port-adapters";

describe("ConnectivityPortAdapter", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("waits for the workspace server before subscribing", () => {
    const unsubscribe = vi.fn();
    const subscribe = vi.fn(() => ({ unsubscribe }));
    const getStatus = vi.fn().mockResolvedValue({ isOnline: true });
    const workspace = {
      connectivity: {
        onStatusChange: { subscribe },
        getStatus: { query: getStatus },
      },
    } as unknown as WorkspaceClient;
    const workspaceServer = new WorkspaceServerService();

    const adapter = new ConnectivityPortAdapter(workspace, workspaceServer);

    expect(subscribe).not.toHaveBeenCalled();
    expect(getStatus).not.toHaveBeenCalled();

    workspaceServer.emit(WorkspaceServerEvent.StatusChanged, {
      status: WorkspaceServerStatus.Ready,
      attempt: 0,
    });

    expect(subscribe).toHaveBeenCalledOnce();
    expect(getStatus).toHaveBeenCalledOnce();

    adapter.dispose();
    expect(unsubscribe).toHaveBeenCalledOnce();
  });
});
