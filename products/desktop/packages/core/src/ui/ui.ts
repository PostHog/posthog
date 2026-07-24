import { TypedEventEmitter } from "@posthog/shared";
import { inject, injectable } from "inversify";
import { UI_AUTH } from "./identifiers";
import type { UiAuth } from "./ports";
import { UIServiceEvent, type UIServiceEvents } from "./schemas";

@injectable()
export class UIService extends TypedEventEmitter<UIServiceEvents> {
  constructor(
    @inject(UI_AUTH)
    private readonly auth: UiAuth,
  ) {
    super();
  }

  openSettings(): void {
    this.emit(UIServiceEvent.OpenSettings, true);
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
}
