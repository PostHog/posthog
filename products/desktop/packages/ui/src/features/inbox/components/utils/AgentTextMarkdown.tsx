import { cn } from "@posthog/quill";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";

/**
 * Short agent-written prose, such as a reason, a caption or a judgment.
 * Agents cite reports and pull requests as Markdown links, so the text renders
 * as Markdown rather than as raw source. The renderer spaces paragraphs for
 * long documents, so the last paragraph drops its bottom margin here.
 */
export function AgentTextMarkdown({
  content,
  className,
}: {
  content: string;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0 break-words [&_p:last-child]:mb-0", className)}>
      <MarkdownRenderer content={content} />
    </div>
  );
}
