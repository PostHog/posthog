import { CodeBlock } from "@posthog/ui/primitives/CodeBlock";
import { memo, useMemo } from "react";
import type { Components } from "react-markdown";
import { MarkdownRenderer } from "./MarkdownRenderer";
import { parseOpenFence, splitMarkdownBlocks } from "./splitMarkdownBlocks";

interface StreamingMarkdownProps {
  content: string;
  componentsOverride?: Partial<Components>;
}

/**
 * Renders streamed agent markdown without re-parsing the whole message on every
 * token. The text is split into top-level blocks: completed blocks keep a stable
 * string so the memoized {@link MarkdownRenderer} skips re-parsing them, and only
 * the growing tail is re-parsed, turning the per-token cost from O(message) into
 * O(last block).
 *
 * While the tail sits inside an unterminated code fence it's shown as plain
 * monospace (no markdown parse, no syntax highlighting) in the same {@link
 * CodeBlock} box the frozen block uses, so closing the fence swaps in the
 * highlight without shifting the layout. Completed messages should use {@link
 * MarkdownRenderer} directly for a single, fully-correct parse.
 */
export const StreamingMarkdown = memo(function StreamingMarkdown({
  content,
  componentsOverride,
}: StreamingMarkdownProps) {
  const blocks = useMemo(() => splitMarkdownBlocks(content), [content]);
  const lastIndex = blocks.length - 1;

  return (
    <>
      {blocks.map((block, index) => {
        const key = `b${index}`;
        const openFence = index === lastIndex ? parseOpenFence(block) : null;
        if (openFence) {
          return (
            <div key={key}>
              {openFence.before.trim() ? (
                <MarkdownRenderer
                  content={openFence.before}
                  componentsOverride={componentsOverride}
                />
              ) : null}
              <CodeBlock size="1" showCopy={false}>
                {openFence.code}
              </CodeBlock>
            </div>
          );
        }
        return (
          <MarkdownRenderer
            key={key}
            content={block}
            componentsOverride={componentsOverride}
          />
        );
      })}
    </>
  );
});
