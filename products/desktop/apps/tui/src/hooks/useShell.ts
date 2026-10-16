import type { Task } from "@posthog/shared";
import { useState } from "react";
import type { Composer } from "../composer";
import { messageOf } from "../errors";
import type { LocalAgent } from "../local";
import type { PiControl } from "../models";
import { shellBlocked } from "../shell";
import {
  type PendingShell,
  type ShellLine,
  shellRuns,
  type TranscriptLine,
} from "../transcript";
import type { FlashNotice } from "./useNotice";

// One shared empty list, so panes with no pending commands keep a stable prop.
const NO_SHELLS: PendingShell[] = [];

export interface Shell {
  runShell: (
    paneId: string,
    taskId: string | null,
    command: string,
    text: string,
  ) => void;
  // The task's ! commands a cloud run has not logged yet.
  shellsFor: (taskId: string | null) => PendingShell[];
}

// A ! command runs where the chat's agent runs; a cloud run shows it here until its log has it.
export function useShell({
  taskOf,
  isLocal,
  localFor,
  control,
  composerFor,
  linesOf,
  flashNotice,
}: {
  taskOf: (taskId: string | null) => Task | undefined;
  isLocal: (taskId: string | null) => taskId is string;
  localFor: (id: string) => Promise<LocalAgent>;
  control: ((taskId: string, runId: string) => PiControl) | undefined;
  composerFor: (paneId: string) => Composer;
  linesOf: (paneId: string) => TranscriptLine[];
  flashNotice: FlashNotice;
}): Shell {
  const [shells, setShells] = useState<Map<string, PendingShell[]>>(new Map());

  const runShell = (
    paneId: string,
    taskId: string | null,
    command: string,
    text: string,
  ): void => {
    const run = taskId ? taskOf(taskId)?.latest_run : undefined;
    const blocked = shellBlocked({
      taskId,
      isLocal: isLocal(taskId),
      run,
      canControl: Boolean(control),
    });
    if (blocked || !taskId) {
      composerFor(paneId).setText(text);
      if (blocked) flashNotice(blocked, { paneId, taskId });
      return;
    }
    if (isLocal(taskId)) {
      localFor(taskId)
        .then((local) => local.control.bash(command))
        .catch((error: unknown) =>
          flashNotice(`Couldn't run it: ${messageOf(error)}`, {
            paneId,
            taskId,
          }),
        );
      return;
    }
    if (!run || !control) return;
    const id = `shell-${globalThis.crypto.randomUUID()}`;
    const seen = shellRuns(linesOf(paneId), command);
    const update = (line: ShellLine | null): void =>
      setShells((current) => {
        const next = new Map(current);
        const others = (current.get(taskId) ?? []).filter(
          (shell) => shell.line.id !== id,
        );
        next.set(taskId, line ? [...others, { line, seen }] : others);
        return next;
      });
    update({ kind: "shell", id, command, status: "in_progress", output: "" });
    control(taskId, run.id)
      .bash(command)
      .then(
        (result) =>
          update({
            kind: "shell",
            id,
            command,
            status:
              result.cancelled || (result.exitCode ?? 0) !== 0
                ? "failed"
                : "completed",
            output: result.output,
          }),
        (error: unknown) => {
          update(null);
          flashNotice(`Couldn't run it: ${messageOf(error)}`, {
            paneId,
            taskId,
          });
        },
      );
  };

  return {
    runShell,
    shellsFor: (taskId) =>
      (taskId ? shells.get(taskId) : undefined) ?? NO_SHELLS,
  };
}
