/**
 * Registers the two small tools that make background jobs manageable
 * (`list_background_jobs`, `cancel_background_job`) plus a consistent
 * renderer for the completion/failure messages `startBackgroundJob` sends,
 * and the background shell and monitor tools built on them (`shells.ts`).
 *
 * The actual "start a background job" primitive lives in `jobs.ts` as a
 * plain function — `subagent` and `workflow` import it directly rather than
 * depending on this extension being loaded first. This extension only owns
 * the shared, cross-caller surface: cancellation, listing, and cleanup.
 */

import type {
  ExtensionAPI,
  ExtensionFactory,
} from "@earendil-works/pi-coding-agent";
import { defineTool } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import {
  BACKGROUND_JOB_MESSAGE_TYPE,
  cancelAllBackgroundJobs,
  cancelBackgroundJob,
  listBackgroundJobs,
} from "./jobs";
import { renderBackgroundJobMessage } from "./render";
import {
  BACKGROUND_SHELL_MESSAGE_TYPE,
  BackgroundShells,
  MAX_READ_LINES,
} from "./shells";

const text = (value: string) => ({
  content: [{ type: "text" as const, text: value }],
  details: {},
});

export function createBackgroundJobsExtension(): ExtensionFactory {
  return (pi) => {
    pi.registerMessageRenderer(
      BACKGROUND_JOB_MESSAGE_TYPE,
      renderBackgroundJobMessage,
    );

    pi.registerTool(
      defineTool({
        name: "list_background_jobs",
        label: "List Background Jobs",
        description:
          "List background jobs currently running (started by subagent/workflow calls with background: true). Returns job ids, labels, and how long each has been running.",
        promptGuidelines: [
          "Use list_background_jobs to check what's still running before starting more background work, or when the user asks for status.",
        ],
        parameters: Type.Object({}),
        execute: async () => {
          const jobs = listBackgroundJobs();
          const text =
            jobs.length === 0
              ? "No background jobs running."
              : jobs
                  .map((job) => {
                    const seconds = Math.round(
                      (Date.now() - job.startedAt) / 1000,
                    );
                    return `- ${job.jobId}: "${job.label}" (running ${seconds}s)`;
                  })
                  .join("\n");
          return { content: [{ type: "text", text }], details: { jobs } };
        },
      }),
    );

    pi.registerTool(
      defineTool({
        name: "cancel_background_job",
        label: "Cancel Background Job",
        description:
          "Cancel a running background job by id (from list_background_jobs). The job's own message will report it as cancelled once teardown finishes.",
        parameters: Type.Object({
          jobId: Type.String({
            description: "Job id, from list_background_jobs",
          }),
        }),
        execute: async (_toolCallId, params) => {
          const cancelled = cancelBackgroundJob(params.jobId);
          const text = cancelled
            ? `Cancelling job ${params.jobId}.`
            : `No running job with id ${params.jobId}.`;
          return { content: [{ type: "text", text }], details: { cancelled } };
        },
      }),
    );

    registerShellTools(pi);

    pi.on("session_shutdown", async () => {
      cancelAllBackgroundJobs();
    });
  };
}

// Shells and monitors; see shells.ts. The status line ("2 shells · 1 monitor") is how an app shows them.
function registerShellTools(pi: ExtensionAPI): void {
  let setStatus: ((text: string | undefined) => void) | undefined;
  const shells = new BackgroundShells(pi, () => setStatus?.(shells.status()));
  pi.on("session_start", async (_event, ctx) => {
    setStatus = (status) => ctx.ui.setStatus("background-shells", status);
  });
  pi.on("session_shutdown", async () => {
    shells.stopAll();
  });
  pi.registerMessageRenderer(
    BACKGROUND_SHELL_MESSAGE_TYPE,
    renderBackgroundJobMessage,
  );

  const monitorParams = Type.Object({
    pattern: Type.String({
      description:
        "Regular expression, matched case-insensitively against each output line, such as 'error|exception' or 'Bundled|ready'",
    }),
    label: Type.Optional(
      Type.String({ description: "Short name for the monitor" }),
    ),
  });

  pi.registerTool(
    defineTool({
      name: "shell_start",
      label: "Start Shell",
      description:
        "Start a long-running command in the background and keep working: a dev server, a mobile app bundler, a test watcher, a log tail, or a CI watch such as `gh pr checks --watch`. Returns a shell id at once. You are told when it exits. Add monitors to be woken when its output matches a pattern.",
      promptGuidelines: [
        "Use shell_start, not bash, for anything that runs until stopped or takes more than a minute, then carry on with other work.",
        "Add a monitor for what you need to react to (errors, a ready line, test failures) instead of polling shell_output.",
        "Stop shells you no longer need with shell_stop.",
      ],
      parameters: Type.Object({
        command: Type.String({ description: "Shell command to run" }),
        cwd: Type.Optional(
          Type.String({
            description: "Working directory; the session's by default",
          }),
        ),
        monitors: Type.Optional(Type.Array(monitorParams)),
      }),
      execute: async (_toolCallId, params, _signal, _onUpdate, ctx) => {
        try {
          const { ack } = shells.start(
            params.command,
            params.cwd ?? ctx.cwd,
            params.monitors,
          );
          return text(ack);
        } catch (error) {
          return text(
            `Couldn't start the shell: ${error instanceof Error ? error.message : String(error)}`,
          );
        }
      },
    }),
  );

  pi.registerTool(
    defineTool({
      name: "shell_output",
      label: "Shell Output",
      description: `Read a background shell's output that you have not read yet, up to ${MAX_READ_LINES} lines; call again for more. With tail, read its last lines instead. Without an id, list every shell and its monitors.`,
      parameters: Type.Object({
        id: Type.Optional(Type.String({ description: "Shell id" })),
        lines: Type.Optional(
          Type.Number({ description: `At most ${MAX_READ_LINES}` }),
        ),
        tail: Type.Optional(Type.Boolean()),
      }),
      execute: async (_toolCallId, params) => {
        if (!params.id) {
          const list = shells.list();
          if (list.length === 0) return text("No background shells.");
          return text(
            list
              .map((shell) =>
                [
                  `- ${shell.id} (${shell.running ? "running" : `exited ${shell.exitCode ?? "?"}`}, ${shell.unread} unread lines): ${shell.command}`,
                  ...shell.monitors.map(
                    (m) =>
                      `  - ${m.id} "${m.label}" /${m.pattern.source}/i, ${m.matches} matches`,
                  ),
                ].join("\n"),
              )
              .join("\n"),
          );
        }
        const read = shells.read(params.id, {
          limit: params.lines,
          tail: params.tail,
        });
        if (!read) return text(`No shell ${params.id}.`);
        return text(
          [
            ...(read.missed > 0
              ? [
                  `(${read.missed} older lines were dropped before you read them)`,
                ]
              : []),
            read.lines.length > 0 ? read.lines.join("\n") : "(no new output)",
            ...(read.more > 0
              ? [`(${read.more} more unread lines; call again for them)`]
              : []),
          ].join("\n"),
        );
      },
    }),
  );

  pi.registerTool(
    defineTool({
      name: "shell_input",
      label: "Shell Input",
      description:
        "Write to a running background shell's stdin, such as `r` to reload an Expo app. A newline is added unless enter is false.",
      parameters: Type.Object({
        id: Type.String(),
        text: Type.String(),
        enter: Type.Optional(Type.Boolean()),
      }),
      execute: async (_toolCallId, params) =>
        text(
          shells.write(
            params.id,
            params.enter === false ? params.text : `${params.text}\n`,
          )
            ? `Sent to ${params.id}.`
            : `${params.id} is not running.`,
        ),
    }),
  );

  pi.registerTool(
    defineTool({
      name: "shell_stop",
      label: "Stop Shell",
      description:
        "Stop a background shell and everything it started. You are told when it has exited.",
      parameters: Type.Object({ id: Type.String() }),
      execute: async (_toolCallId, params) =>
        text(
          shells.stop(params.id)
            ? `Stopping ${params.id}.`
            : `${params.id} is not running.`,
        ),
    }),
  );

  pi.registerTool(
    defineTool({
      name: "monitor",
      label: "Monitor",
      description:
        "Add a monitor to a background shell, which wakes you with matching output lines as they arrive, or remove one. Matches arriving together come as one message, at most one every ten seconds per monitor.",
      parameters: Type.Object({
        action: Type.Union([Type.Literal("add"), Type.Literal("remove")]),
        shellId: Type.Optional(
          Type.String({ description: "For add: the shell to watch" }),
        ),
        pattern: Type.Optional(monitorParams.properties.pattern),
        label: Type.Optional(Type.String()),
        monitorId: Type.Optional(
          Type.String({ description: "For remove: the monitor's id" }),
        ),
      }),
      execute: async (_toolCallId, params) => {
        if (params.action === "remove") {
          if (!params.monitorId) return text("Give the monitorId to remove.");
          return text(
            shells.removeMonitor(params.monitorId)
              ? `Removed ${params.monitorId}.`
              : `No monitor ${params.monitorId}.`,
          );
        }
        if (!params.shellId || !params.pattern)
          return text("Give the shellId and pattern to add a monitor.");
        try {
          const monitor = shells.addMonitor(
            params.shellId,
            params.pattern,
            params.label,
          );
          return text(
            monitor
              ? `Added ${monitor.id} on ${params.shellId}, watching /${monitor.pattern.source}/i.`
              : `No shell ${params.shellId}.`,
          );
        } catch (error) {
          return text(
            `That pattern is not a valid regular expression: ${error instanceof Error ? error.message : String(error)}`,
          );
        }
      },
    }),
  );
}

export default function backgroundJobs(pi: ExtensionAPI): void | Promise<void> {
  return createBackgroundJobsExtension()(pi);
}
