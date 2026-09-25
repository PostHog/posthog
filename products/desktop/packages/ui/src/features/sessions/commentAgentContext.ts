import type { CommentAnchor } from "@posthog/core/comments/anchors";
import type { EditorContent } from "@posthog/core/message-editor/content";

export type CommentResource =
  | { kind: "artifact" | "canvas" | "task"; name: string }
  | { kind: "preview"; name: string; port: number };

export type CommentAgentContext = {
  label: string;
  body: string;
};

const LABEL_LENGTH = 48;
const QUOTE_LABEL_LENGTH = 32;

function truncate(value: string, maxLength: number): string {
  const flat = value.replace(/\s+/g, " ").trim();
  return flat.length > maxLength ? `${flat.slice(0, maxLength - 1)}…` : flat;
}

function inlineCode(value: string): string {
  return `\`${value.replaceAll("`", "'")}\``;
}

function resourceLine(resource: CommentResource): string {
  if (resource.kind === "preview") {
    return `- **Preview** ${resource.name} on port ${resource.port}`;
  }
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
  if (anchor.kind === "element") {
    const port = resource.kind === "preview" ? resource.port : null;
    const page = port ? `http://localhost:${port}${anchor.path}` : anchor.path;
    return {
      label: truncate(
        anchor.text
          ? `${anchor.tag} "${truncate(anchor.text, QUOTE_LABEL_LENGTH)}"`
          : `${anchor.tag} ${anchor.selector}`,
        LABEL_LENGTH,
      ),
      body: [
        `- **Page** ${page}`,
        `- **Element** ${inlineCode(`<${anchor.tag}>`)}${anchor.text ? ` ${truncate(anchor.text, 120)}` : ""}`,
        `- **Selector** ${inlineCode(anchor.selector)}`,
        "",
        "```html",
        anchor.html,
        "```",
      ].join("\n"),
    };
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

export function commentComposerContent({
  comment,
  draftEmpty,
  context,
}: {
  comment: string;
  draftEmpty: boolean;
  context: CommentAgentContext | null;
}): EditorContent {
  const segments: EditorContent["segments"] = [];
  if (!draftEmpty) segments.push({ type: "text", text: "\n" });
  if (context) {
    segments.push(
      {
        type: "chip",
        chip: {
          type: "comment_context",
          id: context.body,
          label: context.label,
        },
      },
      { type: "text", text: " " },
    );
  }
  segments.push({ type: "text", text: comment });
  return { segments };
}
