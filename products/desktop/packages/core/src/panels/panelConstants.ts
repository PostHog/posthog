export const PANEL_SIZES = {
  MIN_PANEL_SIZE: 15,
  DEFAULT_SPLIT: [70, 30] as const,
  EVEN_SPLIT: [50, 50] as const,
  SIZE_DIFF_THRESHOLD: 0.1,
} as const;

export const DEFAULT_PANEL_IDS = {
  ROOT: "root",
  MAIN_PANEL: "main-panel",
  RIGHT_GROUP: "right-group",
  TOP_RIGHT: "top-right",
  BOTTOM_RIGHT: "bottom-right",
} as const;

export const DEFAULT_TAB_IDS = {
  LOGS: "logs",
  SHELL: "shell",
  FILES: "files",
  CHANGES: "changes",
} as const;
