import type { DocSchemas } from "@posthog/api-client/docs";
import { hasAgentMention } from "@posthog/core/canvas/threadTimeline";
import { isTerminalStatus, type Task } from "@posthog/shared/domain-types";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { toast } from "@posthog/ui/primitives/toast";
import { useQuery } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { personName } from "../components/DocPostRow";
import {
  dataPointTaskInput,
  stripAgentMention,
  threadTaskInput,
  watchTaskInput,
} from "./docThreadPrompt";
import { useDocAgentRun } from "./useDocAgentRun";
import { useDiscussionMutations } from "./useDocDiscussions";

export type TaskState = "working" | "waiting" | "failed" | "done";

/** Where the run behind a thread stands, from the task alone. */
export function taskStateOf(task: Task | undefined): TaskState | null {
  if (!task) return null;
  const status = task.latest_run?.status ?? null;
  if (status === null) return "working";
  if (status === "failed" || status === "cancelled") return "failed";
  return isTerminalStatus(status) ? "done" : "working";
}

/** Every post on a thread, the first one included. */
export function threadPosts(
  thread: DocSchemas.DiscussionThread,
): DocSchemas.DiscussionPost[] {
  const { replies, ...first } = thread;
  return [first, ...replies];
}

/** True while the agent owes the thread a reply: it was tagged after its last post. */
export function agentTurnPending(thread: DocSchemas.DiscussionThread): boolean {
  let pending = false;
  for (const post of threadPosts(thread)) {
    if (post.author_kind === "agent") pending = false;
    else if (post.sent_to_agent) pending = true;
  }
  return pending;
}

/**
 * Where the agent stands on a thread. A run stays open between turns, so
 * "working" is read off the thread: the agent is working only while a post
 * waits for its answer.
 */
export function agentStateOf(
  thread: DocSchemas.DiscussionThread | null | undefined,
  task: Task | undefined,
): TaskState | null {
  const state = taskStateOf(task);
  if (state === "working" && thread && !agentTurnPending(thread)) return "done";
  return state;
}

const RUN_POLL_MS = 3_000;

/**
 * One thread, open in the panel.
 *
 * Sending is the one act here. A post between people is a reply. A post that
 * tags the agent goes to the thread's live run, or starts a run when the thread
 * has none yet or its run has ended, with everything said so far.
 */
export function useDocThread(options: {
  docId: string;
  channelId: string;
  docTitle: string;
  thread: DocSchemas.DiscussionThread | null;
  /** The phrase a thread is about to be started on; the first send creates it. */
  pending: { anchorKey: string; anchorText: string } | null;
  onCreated?: (thread: DocSchemas.DiscussionThread) => void;
  onAgentStarted?: () => void;
}) {
  const { thread, pending } = options;
  const actions = useDiscussionMutations(options.docId);
  const run = useDocAgentRun({ channelId: options.channelId });
  const [isSending, setSending] = useState(false);

  const taskId = thread?.task_id ?? null;
  const taskQuery = useQuery({
    ...taskDetailQuery(taskId ?? ""),
    enabled: !!taskId,
    refetchInterval: (query) =>
      agentStateOf(thread, query.state.data) === "working"
        ? RUN_POLL_MS
        : false,
  });
  const task = taskId ? taskQuery.data : undefined;

  const send = useCallback(
    async (content: string) => {
      const text = content.trim();
      if (!text || isSending) return;
      const anchorText = thread?.anchor_text ?? pending?.anchorText ?? "";
      const anchorKey = thread?.anchor_key ?? pending?.anchorKey;
      if (!anchorKey) return;
      const toAgent = hasAgentMention(text);
      setSending(true);
      try {
        // The first tag starts the thread's one task; every later tag goes to
        // that task, live or resumed, so the agent stays the same participant.
        let startedTaskId: string | null = null;
        if (toAgent && !thread?.task_id) {
          const lines = thread
            ? threadPosts(thread)
                .filter((post) => post.author_kind !== "system")
                .map((post) => ({
                  author:
                    post.author_kind === "agent"
                      ? "Agent"
                      : personName(post.created_by),
                  content: post.content,
                }))
            : [];
          // A watch thread with no brief yet compiles again; anything else is a question.
          const compiles = thread?.kind === "watch" && !thread.watch?.brief;
          const input =
            thread?.kind === "data"
              ? dataPointTaskInput({
                  question: stripAgentMention(text) || anchorText,
                  requestId: anchorKey,
                  docTitle: options.docTitle,
                })
              : compiles
                ? watchTaskInput({
                    anchorText,
                    requestId: anchorKey,
                    docTitle: options.docTitle,
                  })
                : threadTaskInput({
                    anchorText,
                    lines,
                    question: text,
                    docTitle: options.docTitle,
                  });
          const created = await run({
            question: input.question,
            description: input.description,
            titleFallback: "Question from a doc",
          });
          startedTaskId = created.id;
          options.onAgentStarted?.();
        }

        if (!thread) {
          const result = await actions.start.mutateAsync({
            content: text,
            anchor_key: anchorKey,
            anchor_text: anchorText.slice(0, 280),
            kind: "text",
            task_id: startedTaskId,
            send_to_agent: toAgent,
          });
          options.onCreated?.(result);
          return;
        }

        const result = await actions.reply.mutateAsync({
          threadId: thread.id,
          body: {
            content: text,
            task_id: startedTaskId,
            send_to_agent: toAgent && !startedTaskId,
          },
        });
        if (result.delivery === "no_run") {
          toast.error("The agent could not be reached", {
            description:
              "Its run has ended and did not resume. Try again in a moment.",
          });
        } else if (result.delivery === "failed") {
          toast.error("The agent did not take the message", {
            description: "It is in the thread. Try again in a moment.",
          });
        }
      } catch (error) {
        toast.error("The message did not send", {
          description: error instanceof Error ? error.message : String(error),
        });
        throw error;
      } finally {
        setSending(false);
      }
    },
    [actions.reply, actions.start, isSending, options, pending, run, thread],
  );

  const setResolved = useCallback(
    (resolved: boolean) => {
      if (!thread) return;
      actions.setResolved.mutate({ threadId: thread.id, resolved });
    },
    [actions.setResolved, thread],
  );

  return { task, send, isSending, setResolved };
}
