import type { CloneStatus } from "./cloneTypes";

const REMOVE_DELAY_SUCCESS_MS = 3000;
const REMOVE_DELAY_ERROR_MS = 5000;

export function removalDelayMsForStatus(status: CloneStatus): number | null {
  if (status === "complete") return REMOVE_DELAY_SUCCESS_MS;
  if (status === "error") return REMOVE_DELAY_ERROR_MS;
  return null;
}
