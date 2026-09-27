import type {
  ITaskBrowserHost,
  TaskBrowserCloseRequest,
  TaskBrowserOpenRequest,
  TaskBrowserPermissionRequest,
} from "@posthog/platform/task-browser";
import { trpcClient } from "../trpc/client";

export const electronTaskBrowserHost: ITaskBrowserHost = {
  onOpenRequest(listener: (request: TaskBrowserOpenRequest) => void) {
    const subscription = trpcClient.taskBrowser.onOpenRequest.subscribe(
      undefined,
      { onData: listener },
    );
    return () => subscription.unsubscribe();
  },
  onCloseRequest(listener: (request: TaskBrowserCloseRequest) => void) {
    const subscription = trpcClient.taskBrowser.onCloseRequest.subscribe(
      undefined,
      { onData: listener },
    );
    return () => subscription.unsubscribe();
  },
  onPermissionRequest(
    listener: (request: TaskBrowserPermissionRequest) => void,
  ) {
    const subscription = trpcClient.taskBrowser.onPermissionRequest.subscribe(
      undefined,
      { onData: listener },
    );
    return () => subscription.unsubscribe();
  },
  onPermissionSettled(listener: (requestId: string) => void) {
    const subscription = trpcClient.taskBrowser.onPermissionSettled.subscribe(
      undefined,
      { onData: (data) => listener(data.requestId) },
    );
    return () => subscription.unsubscribe();
  },
  respondToPermission: (requestId, decision) =>
    trpcClient.taskBrowser.respondToPermission.mutate({ requestId, decision }),
  getSettings: () => trpcClient.taskBrowser.getSettings.query(),
  setSitePolicy: (origin, policy) =>
    trpcClient.taskBrowser.setSitePolicy.mutate({ origin, policy }),
  setFullCdpAccess: (enabled) =>
    trpcClient.taskBrowser.setFullCdpAccess.mutate({ enabled }),
  clearBrowsingData: () => trpcClient.taskBrowser.clearBrowsingData.mutate(),
};
