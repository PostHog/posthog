import {
  ROOT_LOGGER,
  type RootLogger,
  type ScopedLogger,
} from "@posthog/di/logger";
import { type ISpeech, SPEECH_SERVICE } from "@posthog/platform/speech";
import { inject, injectable } from "inversify";
import { composeUtterance } from "./composeUtterance";
import {
  type ISpeechQueue,
  SPEECH_QUEUE_SERVICE,
  SPEECH_SETTINGS_PROVIDER,
  SPEECH_USER_NAME_PROVIDER,
  type SpeechRequest,
  type SpeechSettingsProvider,
  type UserNameProvider,
} from "./identifiers";

export { SPEECH_QUEUE_SERVICE };

/** Max queued utterances (excluding the one currently playing) before we drop. */
const MAX_QUEUE = 3;

interface QueuedUtterance {
  text: string;
  taskId?: string;
  priority: boolean;
}

/**
 * Serializes agent narration so several parallel sessions never talk over each
 * other. One utterance plays at a time; a newer line for a task supersedes its
 * still-queued predecessor; needs-user lines jump the queue and are never
 * dropped; and the queue is capped so a burst can't back up minutes of speech.
 *
 * This is portable orchestration (queue/dedupe/coalesce), so it lives in core
 * and depends only on the host-neutral ISpeech capability plus injected
 * settings/name providers — no tRPC, Node, or Electron.
 */
@injectable()
export class SpeechQueueService implements ISpeechQueue {
  private readonly logger: ScopedLogger;
  private readonly queue: QueuedUtterance[] = [];
  private speaking = false;

  constructor(
    @inject(SPEECH_SERVICE)
    private readonly speech: ISpeech,
    @inject(SPEECH_SETTINGS_PROVIDER)
    private readonly settings: SpeechSettingsProvider,
    @inject(SPEECH_USER_NAME_PROVIDER)
    private readonly userName: UserNameProvider,
    @inject(ROOT_LOGGER)
    rootLogger: RootLogger,
  ) {
    this.logger = rootLogger.scope("speech");
  }

  enqueue(request: SpeechRequest): void {
    const { enabled } = this.settings.get();
    if (!enabled) return;

    const text = composeUtterance({
      text: request.text,
      taskTitle: request.taskTitle,
      needsUser: request.needsUser,
      addressByName: request.addressByName,
      firstName: this.userName.getFirstName(),
    });
    if (!text) return;

    const utterance: QueuedUtterance = {
      text,
      taskId: request.taskId,
      priority: request.needsUser === true,
    };

    // Coalesce: a newer non-priority line for the same task replaces its
    // still-queued predecessor so we speak the freshest narration, not a stale
    // one. Priority lines are kept distinct (each needs answering).
    if (!utterance.priority && utterance.taskId) {
      const idx = this.queue.findIndex(
        (q) => !q.priority && q.taskId === utterance.taskId,
      );
      if (idx !== -1) {
        this.queue[idx] = utterance;
        void this.drain();
        return;
      }
    }

    // Priority lines jump ahead of routine narration.
    if (utterance.priority) {
      const firstNonPriority = this.queue.findIndex((q) => !q.priority);
      if (firstNonPriority === -1) this.queue.push(utterance);
      else this.queue.splice(firstNonPriority, 0, utterance);
    } else {
      this.queue.push(utterance);
    }

    this.enforceCap();
    void this.drain();
  }

  private enforceCap(): void {
    while (this.queue.length > MAX_QUEUE) {
      const idx = this.queue.findIndex((q) => !q.priority);
      if (idx === -1) break; // all priority — never drop
      const [dropped] = this.queue.splice(idx, 1);
      this.logger.warn("Dropped narration; queue backed up", {
        text: dropped.text,
      });
    }
  }

  private async drain(): Promise<void> {
    if (this.speaking) return;
    this.speaking = true;
    try {
      while (this.queue.length > 0) {
        const next = this.queue.shift();
        if (!next) break;
        const { voiceId } = this.settings.get();
        try {
          await this.speech.speak(next.text, { voiceId });
        } catch (err) {
          // Best-effort — a failed line must not stall the queue.
          this.logger.warn("speak failed", { err });
        }
      }
    } finally {
      this.speaking = false;
    }
  }
}
