import {
  type ISpeechQueue,
  SPEECH_QUEUE_SERVICE,
} from "@posthog/core/speech/identifiers";
import type { NotificationTarget } from "@posthog/platform/notifications";
import { inject, injectable } from "inversify";
import {
  ACTIVE_VIEW_PROVIDER,
  type IActiveView,
  type ISpeechNotifySettings,
  SPEECH_NOTIFY_SETTINGS,
} from "./identifiers";
import { routeNotification } from "./routeNotification";
import {
  type SpeechKind,
  type SpeechSource,
  shouldSpeak,
} from "./speechRouting";

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
    const channel = routeNotification({
      appFocused: this.view.hasFocus(),
      viewingTarget: this.view.getActiveTarget(),
      notificationTarget: target,
    });

    if (
      !shouldSpeak(request.kind, request.source, channel, this.settings.get())
    )
      return;

    this.queue.enqueue({
      text: request.text,
      taskTitle: request.taskTitle,
      taskId: request.taskId,
      needsUser: request.kind === "needs_input",
      addressByName: request.addressByName,
    });
  }
}
