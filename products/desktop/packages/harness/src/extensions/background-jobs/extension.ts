/**
 * Registers the two small tools that make background jobs manageable
 * (`list_background_jobs`, `cancel_background_job`) plus a consistent
 * renderer for the completion/failure messages `startBackgroundJob` sends.
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

    pi.on("session_shutdown", async () => {
      cancelAllBackgroundJobs();
    });
  };
}

export default function backgroundJobs(pi: ExtensionAPI): void | Promise<void> {
  return createBackgroundJobsExtension()(pi);
}
