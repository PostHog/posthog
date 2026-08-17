import type { Components } from "react-markdown";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function MarkdownDocumentPreview({
  content,
  components,
}: {
  content: string;
  components?: Components;
}) {
  return (
    <div className="plan-markdown mx-auto max-w-[750px] p-5">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
