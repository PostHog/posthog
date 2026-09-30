import { MermaidDiagram } from "@posthog/ui/primitives/MermaidDiagram";
import { isMermaidCodeBlock } from "@posthog/ui/utils/mermaidBlocks";
import { useMemo } from "react";
import type { Components } from "react-markdown";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const mermaidComponents: Components = {
  code: ({ node, children, className }) => {
    if (isMermaidCodeBlock(node)) {
      return <MermaidDiagram code={String(children).replace(/\n$/, "")} />;
    }
    return <code className={className}>{children}</code>;
  },
  pre: ({ node, children }) => {
    if (isMermaidCodeBlock(node?.children[0])) {
      return children;
    }
    return <pre>{children}</pre>;
  },
};

export function MarkdownDocumentPreview({
  content,
  components,
}: {
  content: string;
  components?: Components;
}) {
  const mergedComponents = useMemo(
    () => ({ ...mermaidComponents, ...components }),
    [components],
  );
  return (
    <div className="plan-markdown mx-auto max-w-[750px] p-5">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={mergedComponents}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
