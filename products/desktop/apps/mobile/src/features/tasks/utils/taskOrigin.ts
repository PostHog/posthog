import {
  Binoculars,
  Broadcast,
  Bug,
  FilmSlate,
  Flask,
  type Icon,
  Lifebuoy,
  Robot,
  SlackLogo,
} from "phosphor-react-native";

/**
 * What created a task, for tasks the user did not type themselves.
 *
 * Mirrors the semantics of desktop's sidebar `TaskIcon` origin map — the same
 * origin should read the same on both surfaces — but not its code: that module
 * is DOM-bound. `user_created` is deliberately absent; a task you typed needs
 * no explanation, and branding every row would make the branding worthless.
 */
export interface TaskOriginMeta {
  Icon: Icon;
  /**
   * Sentence-ready accessibility label. Stored whole rather than composed from
   * a product name so each origin reads naturally ("From inbox", not
   * "From Signal report").
   */
  label: string;
}

const ORIGIN_PRODUCT_META: Record<string, TaskOriginMeta> = {
  slack: { Icon: SlackLogo, label: "From Slack" },
  signal_report: { Icon: Broadcast, label: "From inbox" },
  signals_scout: { Icon: Binoculars, label: "From Signals scout" },
  support_queue: { Icon: Lifebuoy, label: "From support queue" },
  session_summaries: { Icon: FilmSlate, label: "From session summary" },
  error_tracking: { Icon: Bug, label: "From error tracking" },
  eval_clusters: { Icon: Flask, label: "From evals" },
  automation: { Icon: Robot, label: "From automation" },
};

/**
 * Glyph and label for a task's origin, or `null` when the origin needs no
 * badge — the user typed it, the field is missing, or it is an origin this
 * build does not know about yet. An unknown origin is silent on purpose: the
 * server can add products faster than the app ships.
 */
export function getTaskOriginMeta(
  originProduct: string | null | undefined,
): TaskOriginMeta | null {
  if (!originProduct) return null;
  return ORIGIN_PRODUCT_META[originProduct] ?? null;
}
