import type { CloneOperation } from "./cloneTypes";

export interface CloneProgress {
  message: string;
  percent: number;
}

export function parseCloneProgress(
  operation: CloneOperation | null,
): CloneProgress | null {
  if (!operation?.latestMessage) return null;

  const percentMatch = operation.latestMessage.match(/(\d+)%/);
  const percent = percentMatch ? Number.parseInt(percentMatch[1], 10) : 0;

  return {
    message: operation.latestMessage,
    percent,
  };
}
