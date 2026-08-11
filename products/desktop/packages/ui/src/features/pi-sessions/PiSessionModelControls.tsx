import type {
  PiModelSelection,
  PiSessionController,
  PiThinkingLevel,
} from "@posthog/core/pi-runtime/piSessionController";
import type { PiControllerSessionState } from "@posthog/core/pi-runtime/piSessionStore";
import { Skeleton } from "@posthog/quill";
import { isTerminalStatus } from "@posthog/shared/domain-types";
import { useCallback } from "react";
import { PiModelSelector } from "./PiSessionControls";
import {
  getPiPendingConfig,
  usePiPendingConfigStore,
} from "./piPendingConfigStore";
import { usePiModelCatalog } from "./usePiModelCatalog";

interface PiSessionModelControlsProps {
  taskId: string;
  taskRunId?: string;
  session: PiControllerSessionState;
  controller: PiSessionController;
  isOnline: boolean;
  onError: (error: unknown, fallback: string) => void;
}

export function PiSessionModelControls({
  taskId,
  taskRunId,
  session,
  controller,
  isOnline,
  onError,
}: PiSessionModelControlsProps) {
  const isCloudSession = session.cloudStatus !== undefined;
  const isTerminalCloudRun =
    isCloudSession && isTerminalStatus(session.cloudStatus);
  const pendingConfig = usePiPendingConfigStore((state) =>
    getPiPendingConfig(state, taskId, taskRunId),
  );
  const setPendingConfig = usePiPendingConfigStore((state) => state.setConfig);
  const { data: catalog = [], isPending: catalogLoading } =
    usePiModelCatalog(true);
  const controlsDisabled =
    session.status?.isStreaming ||
    session.status?.isCompacting ||
    session.isBashRunning ||
    session.connectionState !== "connected";
  const currentModel = pendingConfig?.model ?? session.status?.model;
  const hasCatalog = catalog.length > 0;
  const models = hasCatalog ? catalog : session.models;
  const modelsLoaded = !catalogLoading && (hasCatalog || session.modelsLoaded);
  const catalogModel = catalog.find(
    (model) =>
      model.provider === currentModel?.provider && model.id === currentModel.id,
  );
  const thinkingLevels = isCloudSession
    ? (catalogModel?.thinkingLevels ?? [])
    : session.thinkingLevels;
  const requestedThinkingLevel =
    pendingConfig?.thinkingLevel ?? session.status?.thinkingLevel;
  const currentThinkingLevel =
    requestedThinkingLevel && thinkingLevels.includes(requestedThinkingLevel)
      ? requestedThinkingLevel
      : thinkingLevels[0];
  const thinkingLevelsLoaded = isCloudSession
    ? !catalogLoading
    : session.thinkingLevelsLoaded;
  const disabled = isTerminalCloudRun ? !isOnline : controlsDisabled;
  const setModel = useCallback(
    (model: PiModelSelection) => {
      if (taskRunId && isTerminalCloudRun) {
        const nextThinkingLevels =
          catalog.find(
            (candidate) =>
              candidate.provider === model.provider &&
              candidate.id === model.id,
          )?.thinkingLevels ?? [];
        const requestedThinkingLevel =
          pendingConfig?.thinkingLevel ?? session.status?.thinkingLevel;
        const thinkingLevel =
          requestedThinkingLevel &&
          nextThinkingLevels.includes(requestedThinkingLevel)
            ? requestedThinkingLevel
            : nextThinkingLevels[0];
        setPendingConfig(taskId, taskRunId, { model, thinkingLevel });
        return;
      }

      void controller
        .setModel(taskId, model)
        .catch((error) => onError(error, "Failed to change Pi model"));
    },
    [
      catalog,
      controller,
      isTerminalCloudRun,
      onError,
      pendingConfig?.thinkingLevel,
      session.status?.thinkingLevel,
      setPendingConfig,
      taskId,
      taskRunId,
    ],
  );
  const setThinkingLevel = useCallback(
    (level: PiThinkingLevel) => {
      if (taskRunId && isTerminalCloudRun) {
        setPendingConfig(taskId, taskRunId, { thinkingLevel: level });
        return;
      }

      void controller
        .setThinkingLevel(taskId, level)
        .catch((error) => onError(error, "Failed to change Pi thinking level"));
    },
    [
      controller,
      isTerminalCloudRun,
      onError,
      setPendingConfig,
      taskId,
      taskRunId,
    ],
  );

  if (!modelsLoaded) {
    return <Skeleton className="h-7 w-32 bg-foreground/15" />;
  }

  const supportsThinking = thinkingLevels.some((level) => level !== "off");
  return (
    <PiModelSelector
      models={models}
      currentModel={currentModel}
      thinkingLevel={
        thinkingLevelsLoaded && supportsThinking
          ? currentThinkingLevel
          : undefined
      }
      thinkingLevels={thinkingLevels}
      disabled={disabled}
      onChange={setModel}
      onThinkingLevelChange={setThinkingLevel}
    />
  );
}
