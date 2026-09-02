export type DialogSeverity = "info" | "warning" | "error" | "question";

export interface ConfirmOptions {
  title: string;
  message: string;
  detail?: string;
  options: string[];
  defaultIndex?: number;
  cancelIndex?: number;
  severity?: DialogSeverity;
}

export interface PickFileOptions {
  title?: string;
  multiple?: boolean;
  directories?: boolean;
  filesAndDirectories?: boolean;
  createDirectories?: boolean;
}

export interface IDialog {
  confirm(options: ConfirmOptions): Promise<number>;
  pickFile(options: PickFileOptions): Promise<string[]>;
}

export const DIALOG_SERVICE = Symbol.for("posthog.platform.dialog");
