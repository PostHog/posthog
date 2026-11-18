import {
  type ISpeechQueue,
  SPEECH_QUEUE_SERVICE,
} from "@posthog/core/speech/identifiers";
import type { NotificationTarget } from "@posthog/platform/notifications";
import { logger } from "@posthog/ui/shell/logger";
import { inject, injectable } from "inversify";
import {
  ACTIVE_VIEW_PROVIDER,
  type IActiveView,
  type ISpeechNotifySettings,
  SPEECH_NOTIFY_SETTINGS,
} from "./identifiers";
import { describeTarget, routeNotification } from "./routeNotification";
import {
  type SpeechKind,
  type SpeechSource,
  shouldSpeak,
} from "./speechRouting";

const log = logger.scope("notifications");

export interface SpeakRequest {
  text: string;
  kind: SpeechKind;
  /** Agent `speak` tool call, or the deterministic turn/permission backstop. */
  source: SpeechSource;
  taskTitle: string;
  taskId?: string;
  /** Address the user by name ("Hey <name>,") — agent lines only, not backstop. */
  addressByName?: boolean;
}

/**
 * The speech channel's decision point: applies the user's spoken-notification
 * settings and focus routing (reusing routeNotification, so "quiet for the task
 * I'm watching" comes for free), then hands the surviving line to the core
 * SpeechQueueService for serialization. Mirrors NotificationBus but for voice.
 */
@injectable()
export class SpeechNotifier {
  constructor(
    @inject(ACTIVE_VIEW_PROVIDER)
    private readonly view: IActiveView,
    @inject(SPEECH_NOTIFY_SETTINGS)
    private readonly settings: ISpeechNotifySettings,
    @inject(SPEECH_QUEUE_SERVICE)
    private readonly queue: ISpeechQueue,
  ) {}

  speak(request: SpeakRequest): void {
    const target: NotificationTarget | undefined = request.taskId
      ? { kind: "task", taskId: request.taskId }
      : undefined;
    // Read focus and route once: a focus change between the decision and the
    // log line would otherwise leave the two contradicting each other.
    const appFocused = this.view.hasFocus();
    const viewingTarget = this.view.getActiveTarget();
    const channel = routeNotification({
      appFocused,
      viewingTarget,
      notificationTarget: target,
    });

    const speaks = shouldSpeak(
      request.kind,
      request.source,
      channel,
      this.settings.get(),
    );

    // Speech is the other way the app makes a noise, so it logs the same
    // decision shape as the notification bus.
    log.info("Speech notification", {
      kind: request.kind,
      source: request.source,
      channel,
      spoke: speaks,
      target: describeTarget(target),
      viewingTarget: describeTarget(viewingTarget),
      appFocused,
    });

    if (!speaks) return;

    this.queue.enqueue({
      text: request.text,
      taskTitle: request.taskTitle,
      taskId: request.taskId,
      needsUser: request.kind === "needs_input",
      addressByName: request.addressByName,
    });
  }
}
