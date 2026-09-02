export interface IClipboard {
  writeText(text: string): Promise<void>;
}

export const CLIPBOARD_SERVICE = Symbol.for("posthog.platform.clipboard");
