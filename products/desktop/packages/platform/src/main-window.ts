export interface IMainWindow {
  focus(): void;
  isFocused(): boolean;
  isMinimized(): boolean;
  restore(): void;
  onFocus(handler: () => void): () => void;
  zoomIn(): void;
  zoomOut(): void;
  resetZoom(): void;
}

export const MAIN_WINDOW_SERVICE = Symbol.for("posthog.platform.mainWindow");
