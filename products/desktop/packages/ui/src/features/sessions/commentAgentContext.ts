import type { CommentAnchor } from "@posthog/core/comments/anchors";
import type { CommentAgentContext } from "@posthog/core/sessions/commentToAgent";

export type CommentResource = {
  kind: "artifact" | "canvas" | "task";
  name: string;
};

const LABEL_LENGTH = 48;
const QUOTE_LABEL_LENGTH = 32;

function truncate(value: string, maxLength: number): string {
  const flat = value.replace(/\s+/g, " ").trim();
  return flat.length > maxLength ? `${flat.slice(0, maxLength - 1)}…` : flat;
}

function resourceLine(resource: CommentResource): string {
  const kind = resource.kind[0].toUpperCase() + resource.kind.slice(1);
  return `- **${kind}** ${resource.name}`;
}

export function commentAgentContext(
  anchor: CommentAnchor | null,
  resource: CommentResource,
): CommentAgentContext | null {
  if (!anchor || (anchor.kind === "document" && resource.kind === "task")) {
    return null;
  }
  if (anchor.kind === "text") {
    return {
      label: truncate(
        `${resource.name} "${truncate(anchor.quote, QUOTE_LABEL_LENGTH)}"`,
        LABEL_LENGTH + QUOTE_LABEL_LENGTH,
      ),
      body: [
        resourceLine(resource),
        "",
        ...anchor.quote.split("\n").map((line) => `> ${line}`),
      ].join("\n"),
    };
  }
  if (anchor.kind === "region") {
    const percent = (value: number) => `${Math.round(value * 100)}%`;
    return {
      label: truncate(`${resource.name} (region)`, LABEL_LENGTH),
      body: [
        resourceLine(resource),
        `- **Region** left ${percent(anchor.x)}, top ${percent(anchor.y)}, width ${percent(anchor.width)}, height ${percent(anchor.height)}`,
      ].join("\n"),
    };
  }
  return {
    label: truncate(resource.name, LABEL_LENGTH),
    body: resourceLine(resource),
  };
}

export function withScreenshot(
  context: CommentAgentContext | null,
  screenshot: string | null,
): CommentAgentContext | null {
  return context && screenshot ? { ...context, screenshot } : context;
}
