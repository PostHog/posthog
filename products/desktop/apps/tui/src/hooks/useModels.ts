import type { Task } from "@posthog/shared";
import { useRef, useState } from "react";
import type { Composer } from "../composer";
import { messageOf } from "../errors";
import { findPane, type LayoutState } from "../layout";
import type { LocalSession } from "../local";
import {
  type ModelChoice,
  modelSheet,
  type PiControl,
  type RunCommand,
} from "../models";
import type { Sheet } from "../sheet";
import { indicatorFor } from "../sidebar";
import type { Notice } from "./useNotice";

export interface Models {
  // Opens /model: a live chat switches now, any other chat holds the pick until its run is live.
  openModelSheet: (paneId: string, task: Task | undefined) => void;
  // Called when a pane's run goes live: shows its slash commands and applies a held pick.
  onRunLive: (paneId: string, taskId: string, runId: string) => void;
  modelName: (paneId: string, taskId: string | null) => string | undefined;
}

// Models and each live run's own slash commands, over pi/rpc (cloud) or the local agent.
export function useModels({
  layout,
  isLocal,
  localSessions,
  control,
  composerFor,
  openModal,
  notice: { flashNotice, showNotice, clearNotice },
}: {
  layout: LayoutState;
  isLocal: (taskId: string | null) => taskId is string;
  localSessions: Map<string, LocalSession>;
  control: ((taskId: string, runId: string) => PiControl) | undefined;
  composerFor: (paneId: string) => Composer;
  openModal: (
    paneId: string,
    sheet: Sheet,
    choose: (index: number) => void,
  ) => void;
  notice: Notice;
}): Models {
  // The last list a live run gave us, each task's model, and picks held until a pane's run is live.
  const knownModels = useRef<ModelChoice[] | null>(null);
  const [taskModels, setTaskModels] = useState<Map<string, ModelChoice>>(
    new Map(),
  );
  const [heldModels, setHeldModels] = useState<Map<string, ModelChoice>>(
    new Map(),
  );
  // Keyed by task and run: every local chat's run id is "local".
  const appliedHolds = useRef(new Set<string>());

  const openModelSheet = (paneId: string, task: Task | undefined): void => {
    const run = task?.latest_run;
    const pane = findPane(layout, paneId);
    const localSession = isLocal(pane?.taskId ?? null)
      ? localSessions.get(pane?.taskId as string)
      : undefined;
    const target = localSession
      ? { control: localSession.control, taskId: pane?.taskId as string }
      : task && run && control && indicatorFor(task, false) === "alive"
        ? { control: control(task.id, run.id), taskId: task.id }
        : null;
    if (target) {
      const live = target.control;
      showNotice("Loading models…");
      live.models().then(
        ({ available, current }) => {
          clearNotice();
          knownModels.current = available;
          if (current)
            setTaskModels((models) =>
              new Map(models).set(target.taskId, current),
            );
          openModal(
            paneId,
            modelSheet(available, current, "Switches this chat's model now."),
            (index) => {
              const model = available[index];
              live.setModel(model).then(
                () =>
                  setTaskModels((models) =>
                    new Map(models).set(target.taskId, model),
                  ),
                (error: unknown) =>
                  flashNotice(`Couldn't switch model: ${messageOf(error)}`),
              );
            },
          );
        },
        (error: unknown) =>
          flashNotice(`Couldn't load models: ${messageOf(error)}`),
      );
      return;
    }
    const available = knownModels.current;
    if (!available) {
      flashNotice(
        "The model list comes from a running chat. Send a message first.",
      );
      return;
    }
    const held =
      heldModels.get(paneId) ?? (task ? taskModels.get(task.id) : undefined);
    openModal(
      paneId,
      modelSheet(
        available,
        held ?? null,
        "Applies once this chat's run starts.",
      ),
      (index) =>
        setHeldModels((models) =>
          new Map(models).set(paneId, available[index]),
        ),
    );
  };

  // Each live run's slash commands, fetched once and handed to the composer of the pane showing it.
  const runCommands = useRef(new Map<string, RunCommand[] | "loading">());
  const commandsShown = useRef(new Map<string, string>());
  const showRunCommands = (
    paneId: string,
    taskId: string,
    runId: string,
  ): void => {
    if (!control) return;
    const key = `${taskId}:${runId}`;
    const commands = runCommands.current.get(key);
    if (commands === undefined) {
      runCommands.current.set(key, "loading");
      control(taskId, runId)
        .commands()
        .then(
          (loaded) => {
            runCommands.current.set(key, loaded);
            showRunCommands(paneId, taskId, runId);
          },
          // No retry: a run that cannot list commands just gets the built-in ones.
          () => runCommands.current.set(key, []),
        );
      return;
    }
    if (commands === "loading" || commandsShown.current.get(paneId) === key)
      return;
    commandsShown.current.set(paneId, key);
    composerFor(paneId).setCommands(commands);
  };

  // A pick made while the run was not live is applied as soon as its sandbox is.
  const onRunLive = (paneId: string, taskId: string, runId: string): void => {
    showRunCommands(paneId, taskId, runId);
    const key = `${taskId}:${runId}`;
    const held = heldModels.get(paneId);
    if (!held || !control || appliedHolds.current.has(key)) return;
    appliedHolds.current.add(key);
    control(taskId, runId)
      .setModel(held)
      .then(
        () => {
          setTaskModels((models) => new Map(models).set(taskId, held));
          setHeldModels((models) => {
            const next = new Map(models);
            next.delete(paneId);
            return next;
          });
        },
        (error: unknown) =>
          flashNotice(`Couldn't switch model: ${messageOf(error)}`),
      );
  };

  return {
    openModelSheet,
    onRunLive,
    modelName: (paneId, taskId) =>
      heldModels.get(paneId)?.name ??
      (taskId ? taskModels.get(taskId)?.name : undefined),
  };
}
