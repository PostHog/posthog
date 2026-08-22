import { useSpendGuardrails } from "./useSpendGuardrails";

/** Mounts the spend-line watcher at the app root. Renders nothing. */
export function SpendGuardrailsHost() {
  useSpendGuardrails();
  return null;
}
