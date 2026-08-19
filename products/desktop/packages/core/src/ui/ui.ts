import {
  DEEP_LINK_SERVICE,
  type IDeepLinkRegistry,
} from "@posthog/platform/deep-link";
import {
  type IMainWindow,
  MAIN_WINDOW_SERVICE,
} from "@posthog/platform/main-window";
import { TypedEventEmitter } from "@posthog/shared";
import { inject, injectable } from "inversify";
import { UI_AUTH } from "./identifiers";
import type { UiAuth } from "./ports";
import {
  type OpenSettingsPayload,
  UIServiceEvent,
  type UIServiceEvents,
} from "./schemas";

@injectable()
export class UIService extends TypedEventEmitter<UIServiceEvents> {
  private pendingSettingsLink: OpenSettingsPayload | null = null;

  constructor(
    @inject(UI_AUTH)
    private readonly auth: UiAuth,
    @inject(DEEP_LINK_SERVICE)
    private readonly deepLinkService: IDeepLinkRegistry,
    @inject(MAIN_WINDOW_SERVICE)
    private readonly mainWindow: IMainWindow,
  ) {
    super();

    this.deepLinkService.registerHandler("usage", (path) =>
      this.handleUsageLink(path),
    );
  }

  openSettings(category: string = "plan-usage"): void {
    this.emit(UIServiceEvent.OpenSettings, { category });
  }

  newTask(): void {
    this.emit(UIServiceEvent.NewTask, true);
  }

  resetLayout(): void {
    this.emit(UIServiceEvent.ResetLayout, true);
  }

  clearStorage(): void {
    this.emit(UIServiceEvent.ClearStorage, true);
  }

  async invalidateToken(): Promise<void> {
    await this.auth.invalidateAccessTokenForTest();
    this.emit(UIServiceEvent.InvalidateToken, true);
  }

  /** Drain a usage deep link that arrived before the renderer subscribed. */
  consumePendingSettingsLink(): OpenSettingsPayload | null {
    const pending = this.pendingSettingsLink;
    this.pendingSettingsLink = null;
    return pending;
  }

  private handleUsageLink(path: string): boolean {
    const segment = path.split("/")[0];
    const decoded = segment === "" ? "" : safeDecode(segment);
    const category = decoded === "" ? "plan-usage" : decoded;
    const payload: OpenSettingsPayload = { category };

    if (this.listenerCount(UIServiceEvent.OpenSettings) > 0) {
      this.emit(UIServiceEvent.OpenSettings, payload);
    } else {
      this.pendingSettingsLink = payload;
    }

    if (this.mainWindow.isMinimized()) this.mainWindow.restore();
    this.mainWindow.focus();
    return true;
  }
}

function safeDecode(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}
