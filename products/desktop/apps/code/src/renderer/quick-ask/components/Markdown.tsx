import React from "react";

/**
 * Minimal markdown for streamed PostHog AI answers: paragraphs, bullet lists,
 * headings (rendered bold), `code`, **bold**. Deliberately not a full parser;
 * anything unrecognized renders as plain text.
 */

function InlineRuns({ text }: { text: string }): React.JSX.Element {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return (
    <>
      {parts.map((part, index) => {
        // Parts are a static split of one snapshot string; a position-derived
        // key is stable here.
        const key = `${index}:${part}`;
        if (part.startsWith("**") && part.endsWith("**")) {
          return <strong key={key}>{part.slice(2, -2)}</strong>;
        }
        if (part.startsWith("`") && part.endsWith("`")) {
          return <code key={key}>{part.slice(1, -1)}</code>;
        }
        return <React.Fragment key={key}>{part}</React.Fragment>;
      })}
    </>
  );
}

interface Block {
  kind: "paragraph" | "heading" | "list";
  lines: string[];
}

function toBlocks(markdown: string): Block[] {
  const blocks: Block[] = [];
  for (const raw of markdown.split(/\n{2,}/)) {
    const text = raw.trim();
    if (!text) continue;
    const lines = text.split("\n").map((line) => line.trim());
    if (lines.every((line) => /^[-*] /.test(line))) {
      blocks.push({ kind: "list", lines: lines.map((line) => line.slice(2)) });
    } else if (lines.length === 1 && /^#{1,6} /.test(lines[0])) {
      blocks.push({
        kind: "heading",
        lines: [lines[0].replace(/^#{1,6} /, "")],
      });
    } else {
      blocks.push({ kind: "paragraph", lines });
    }
  }
  return blocks;
}

export function Markdown({ text }: { text: string }): React.JSX.Element {
  const blocks = toBlocks(text);
  return (
    <>
      {blocks.map((block, index) => {
        const key = `${index}:${block.lines[0] ?? ""}`;
        if (block.kind === "list") {
          return (
            <ul key={key}>
              {block.lines.map((line, lineIndex) => (
                <li key={`${lineIndex}:${line}`}>
                  <InlineRuns text={line} />
                </li>
              ))}
            </ul>
          );
        }
        if (block.kind === "heading") {
          return (
            <p key={key}>
              <strong>
                <InlineRuns text={block.lines[0]} />
              </strong>
            </p>
          );
        }
        return (
          <p key={key}>
            <InlineRuns text={block.lines.join(" ")} />
          </p>
        );
      })}
    </>
  );
}
