import type { Task } from "@posthog/shared";
import { useRef, useState } from "react";
import type { Composer } from "../composer";
import { messageOf } from "../errors";
import { findPane, type LayoutState } from "../layout";
import type { LocalAgent } from "../local";
import {
  type Effort,
  effortSheet,
  type ModelChoice,
  modelSheet,
  modelWithEffort,
  type PiControl,
  type RunCommand,
  STARTING_MODEL,
} from "../models";
import type { Sheet } from "../sheet";
import { indicatorFor } from "../sidebar";
import type { Notice } from "./useNotice";

export interface Models {
  // Opens /model: a live chat switches now, any other chat holds the pick until its run is live.
  openModelSheet: (paneId: string, task: Task | undefined) => void;
  // Opens /effort, which works the same way.
  openEffortSheet: (paneId: string, task: Task | undefined) => void;
  // /compact: summarises a live chat's older messages, focused by the instructions if given.
  compact: (
    paneId: string,
    task: Task | undefined,
    instructions: string,
  ) => void;
  // Called when a pane's run goes live: shows its slash commands, applies held picks and reads what the run is on.
  onRunLive: (paneId: string, taskId: string, runId: string) => void;
  // Called when a new chat gets its task, so the model it starts on stays shown until its run is live.
  onChatStarted: (paneId: string, taskId: string) => void;
  // The model and effort a pane's chat runs on, for its title.
  modelLabel: (paneId: string, taskId: string | null) => string | undefined;
}

const without = <V>(map: Map<string, V>, key: string): Map<string, V> => {
  const next = new Map(map);
  next.delete(key);
  return next;
};

// Models, efforts and each live run's own slash commands, over pi/rpc (cloud) or the local agent.
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
  localSessions: Map<string, LocalAgent>;
  control: ((taskId: string, runId: string) => PiControl) | undefined;
  composerFor: (paneId: string) => Composer;
  openModal: (
    paneId: string,
    sheet: Sheet,
    choose: (index: number) => void,
  ) => void;
  notice: Notice;
}): Models {
  // The last lists a live run gave us, what each task is on, and picks held until a pane's run is live.
  // Efforts depend on the model, so a held effort comes from the last list and pi moves it to the nearest level the model supports.
  const knownModels = useRef<ModelChoice[] | null>(null);
  const knownEfforts = useRef<Effort[] | null>(null);
  const [taskModels, setTaskModels] = useState<Map<string, ModelChoice>>(
    new Map(),
  );
  const [heldModels, setHeldModels] = useState<Map<string, ModelChoice>>(
    new Map(),
  );
  const [taskEfforts, setTaskEfforts] = useState<Map<string, Effort>>(
    new Map(),
  );
  const [heldEfforts, setHeldEfforts] = useState<Map<string, Effort>>(
    new Map(),
  );
  // Keyed by task and run: every local chat's run id is "local".
  const synced = useRef(new Set<string>());

  // What the run says it is on, which can differ from what it was started with.
  const readRun = async (taskId: string, live: PiControl): Promise<void> => {
    const [models, efforts] = await Promise.all([
      live.models(),
      live.efforts(),
    ]);
    knownModels.current = models.available;
    knownEfforts.current = efforts.available;
    const { current } = models;
    if (current) setTaskModels((known) => new Map(known).set(taskId, current));
    const effort = efforts.current;
    if (effort) setTaskEfforts((known) => new Map(known).set(taskId, effort));
  };

  // The pane's chat when its run can take a switch now.
  const liveTarget = (
    paneId: string,
    task: Task | undefined,
  ): { control: PiControl; taskId: string } | null => {
    const run = task?.latest_run;
    const taskId = findPane(layout, paneId)?.taskId ?? null;
    const localSession = isLocal(taskId)
      ? localSessions.get(taskId)
      : undefined;
    if (localSession && taskId)
      return { control: localSession.control, taskId };
    return task && run && control && indicatorFor(task, false) === "alive"
      ? { control: control(task.id, run.id), taskId: task.id }
      : null;
  };

  const openModelSheet = (paneId: string, task: Task | undefined): void => {
    const target = liveTarget(paneId, task);
    if (target) {
      const live = target.control;
      showNotice("Loading models…", { paneId });
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
                () => {
                  setTaskModels((models) =>
                    new Map(models).set(target.taskId, model),
                  );
                  // The new model can move the effort to the nearest level it supports.
                  readRun(target.taskId, live).catch(() => {});
                },
                (error: unknown) =>
                  flashNotice(`Couldn't switch model: ${messageOf(error)}`, {
                    paneId,
                  }),
              );
            },
          );
        },
        (error: unknown) =>
          flashNotice(`Couldn't load models: ${messageOf(error)}`, { paneId }),
      );
      return;
    }
    const available = knownModels.current;
    if (!available) {
      flashNotice(
        "The model list comes from a running chat. Send a message first.",
        { paneId },
      );
      return;
    }
    const held =
      heldModels.get(paneId) ??
      (task ? taskModels.get(task.id) : STARTING_MODEL);
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

  const openEffortSheet = (paneId: string, task: Task | undefined): void => {
    const target = liveTarget(paneId, task);
    if (target) {
      const live = target.control;
      showNotice("Loading efforts…", { paneId });
      live.efforts().then(
        ({ available, current }) => {
          clearNotice();
          knownEfforts.current = available;
          if (current)
            setTaskEfforts((efforts) =>
              new Map(efforts).set(target.taskId, current),
            );
          openModal(
            paneId,
            effortSheet(available, current, "Switches this chat's effort now."),
            (index) => {
              const effort = available[index];
              live.setEffort(effort).then(
                () =>
                  setTaskEfforts((efforts) =>
                    new Map(efforts).set(target.taskId, effort),
                  ),
                (error: unknown) =>
                  flashNotice(`Couldn't switch effort: ${messageOf(error)}`, {
                    paneId,
                  }),
              );
            },
          );
        },
        (error: unknown) =>
          flashNotice(`Couldn't load efforts: ${messageOf(error)}`, { paneId }),
      );
      return;
    }
    const available = knownEfforts.current;
    if (!available) {
      flashNotice(
        "The effort list comes from a running chat. Send a message first.",
        { paneId },
      );
      return;
    }
    const held =
      heldEfforts.get(paneId) ?? (task ? taskEfforts.get(task.id) : undefined);
    openModal(
      paneId,
      effortSheet(
        available,
        held ?? null,
        "Applies once this chat's run starts.",
      ),
      (index) =>
        setHeldEfforts((efforts) =>
          new Map(efforts).set(paneId, available[index]),
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

  // Picks held while the run was not live are applied as soon as it is, and then the run says what it is on.
  const onRunLive = (paneId: string, taskId: string, runId: string): void => {
    showRunCommands(paneId, taskId, runId);
    if (!control) return;
    const key = `${taskId}:${runId}`;
    if (synced.current.has(key)) return;
    synced.current.add(key);
    const live = control(taskId, runId);
    const model = heldModels.get(paneId);
    const effort = heldEfforts.get(paneId);
    const applyHeld = async (): Promise<void> => {
      try {
        // The model goes first, because switching it can move the effort.
        if (model) await live.setModel(model);
        if (effort) await live.setEffort(effort);
      } catch (error) {
        flashNotice(`Couldn't apply your pick: ${messageOf(error)}`, {
          paneId,
        });
      }
      if (model) setHeldModels((models) => without(models, paneId));
      if (effort) setHeldEfforts((efforts) => without(efforts, paneId));
      await readRun(taskId, live);
    };
    // No retry: the chat keeps what it was started with, and /model or /effort reads it again.
    applyHeld().catch(() => {});
  };

  const onChatStarted = (paneId: string, taskId: string): void =>
    setTaskModels((models) =>
      new Map(models).set(taskId, heldModels.get(paneId) ?? STARTING_MODEL),
    );

  const compact = (
    paneId: string,
    task: Task | undefined,
    instructions: string,
  ): void => {
    const target = liveTarget(paneId, task);
    if (!target) {
      flashNotice("Compacting needs a running chat. Send a message first", {
        paneId,
      });
      return;
    }
    // The chat's events show the compaction, its wait and what it freed. pi's request gives up after 30
    // seconds while a long compaction carries on, so only another error is a failure.
    target.control
      .compact(instructions || undefined)
      .catch((error: unknown) => {
        const message = messageOf(error);
        if (!/timeout|timed out/i.test(message))
          flashNotice(`Couldn't compact: ${message}`, { paneId });
      });
  };

  return {
    openModelSheet,
    openEffortSheet,
    compact,
    onRunLive,
    onChatStarted,
    // A chat with no task yet shows the model its run will start on. Its effort shows once the run reports it.
    modelLabel: (paneId, taskId) =>
      modelWithEffort(
        heldModels.get(paneId)?.name ??
          (taskId ? taskModels.get(taskId)?.name : STARTING_MODEL.name),
        heldEfforts.get(paneId) ??
          (taskId ? taskEfforts.get(taskId) : undefined),
      ),
  };
}
