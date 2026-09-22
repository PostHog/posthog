import {
  detectInlineArtifact as detectFromCall,
  type InlineArtifact,
} from "@posthog/core/sessions/inlineArtifacts";

export type { InlineArtifact };

export function toolResultText(result: unknown): string {
  if (typeof result === "string") return result;
  try {
    return JSON.stringify(result) ?? "";
  } catch {
    return "";
  }
}

export function detectInlineArtifact(toolData: {
  meta?: unknown;
  status: string;
  args?: Record<string, unknown>;
  result?: unknown;
}): InlineArtifact | null {
  return detectFromCall({
    status: toolData.status,
    meta: toolData.meta,
    rawInput: toolData.args,
    getOutputText: () => toolResultText(toolData.result),
  });
}
