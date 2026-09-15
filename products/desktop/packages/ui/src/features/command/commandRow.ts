import type { CommandMenuAction } from "@posthog/shared/analytics-events";
import type { ReactNode } from "react";

export type Command = {
  id: string;
  label: string;
  /** Muted trailing detail shown at the row's right edge, e.g. a task's space. */
  detail?: string;
  detailPrefix?: string;
  /** Muted second line under the label: what the task list says about a row. */
  subtitle?: ReactNode;
  keywords?: string;
  icon: ReactNode;
  action: CommandMenuAction;
  /** Channel in scope for the bluebird open-channel / open-task actions. */
  channelId?: string;
  /** Hotkey string (e.g. "mod+b") shown right-aligned when present. */
  shortcut?: string;
  /** Where this row lives, for a mod-click or mod+enter that opens a new tab. */
  href?: string;
  /** Running this keeps the palette open (e.g. completing a filter token). */
  keepOpen?: boolean;
  onRun: () => void;
};

export type CommandSection = { label: string; items: Command[] };
