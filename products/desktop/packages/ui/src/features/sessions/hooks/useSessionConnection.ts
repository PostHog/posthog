import {
  type ReconcileSessionState,
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { useService } from "@posthog/di/react";
import type { Task } from "@posthog/shared/domain-types";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import type { AgentSession } from "@posthog/ui/features/sessions/sessionStore";
import { useConnectivity } from "@posthog/ui/hooks/useConnectivity";
import { useUserPresence } from "@posthog/ui/hooks/useUserPresence";
import { logger } from "@posthog/ui/shell/logger";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";
import { useChatTitleGenerator } from "./useChatTitleGenerator";

const log = logger.scope("session-connection");

interface UseSessionConnectionOptions {
  taskId: string;
  task: Task;
  session: AgentSession | undefined;
  repoPath: string | null;
  isCloud: boolean;
  isSuspended?: boolean;
}

export function useSessionConnection({
  task,
  session,
  repoPath,
  isCloud,
  isSuspended,
}: UseSessionConnectionOptions) {
  const queryClient = useQueryClient();
  const { isOnline } = useConnectivity();
  const cloudAuthState = useAuthStateValue((state) => state);
  const sessionService = useService<SessionService>(SESSION_SERVICE);
  // A mounted view used to heartbeat (and auto-reconnect) forever, pinning a
  // ~300-400MB agent process per visible task even when the user walked away.
  // Presence-gate both so the workspace-server idle timeout can reclaim the
  // agent; the existing idle-kill reconcile path restores it on return.
  const userPresent = useUserPresence();

  useChatTitleGenerator(task);

  const taskRunId = session?.taskRunId;
  const sessionTaskId = session?.taskId;
  const sessionTaskTitle = session?.taskTitle;
  const sessionStatus = session?.status;
  const sessionIsCloud = session?.isCloud;
  const sessionIdleKilled = session?.idleKilled;
  const needsEventCount = !repoPath && !isCloud;
  const sessionEventCount = needsEventCount ? (session?.events.length ?? 0) : 0;
  const connectionSession = useMemo<ReconcileSessionState | undefined>(() => {
    if (
      taskRunId === undefined ||
      sessionTaskId === undefined ||
      sessionTaskTitle === undefined ||
      sessionStatus === undefined
    ) {
      return undefined;
    }
    return {
      taskRunId,
      taskId: sessionTaskId,
      taskTitle: sessionTaskTitle,
      status: sessionStatus,
      isCloud: sessionIsCloud,
      idleKilled: sessionIdleKilled,
      eventCount: sessionEventCount,
    };
  }, [
    taskRunId,
    sessionTaskId,
    sessionTaskTitle,
    sessionStatus,
    sessionIsCloud,
    sessionIdleKilled,
    sessionEventCount,
  ]);

  useEffect(() => {
    return sessionService.registerMountedTask(task.id);
  }, [task.id, sessionService]);

  useEffect(() => {
    if (!taskRunId) return;
    if (!userPresent) {
      log.info("User away — pausing activity heartbeat", { taskRunId });
      return;
    }
    return sessionService.startActivityHeartbeat(taskRunId);
  }, [taskRunId, sessionService, userPresent]);

  useEffect(() => {
    return sessionService.reconcileTaskConnection({
      task,
      session: connectionSession,
      repoPath,
      isCloud,
      // While the user is away, freeze local reconciling too — otherwise the
      // idle-kill auto-reconnect would respawn the agent process seconds
      // after the server reclaimed it. Cloud reconcile ignores this flag.
      isSuspended: isSuspended || !userPresent,
      isOnline,
      cloudAuth: {
        status: cloudAuthState.status,
        bootstrapComplete: cloudAuthState.bootstrapComplete,
        projectId: cloudAuthState.currentProjectId,
        cloudRegion: cloudAuthState.cloudRegion,
      },
      onCloudStatusChange: () => {
        queryClient.invalidateQueries({ queryKey: ["tasks"] });
      },
    });
  }, [
    task,
    connectionSession,
    repoPath,
    isCloud,
    isSuspended,
    userPresent,
    isOnline,
    cloudAuthState.status,
    cloudAuthState.bootstrapComplete,
    cloudAuthState.currentProjectId,
    cloudAuthState.cloudRegion,
    queryClient,
    sessionService,
  ]);
}
