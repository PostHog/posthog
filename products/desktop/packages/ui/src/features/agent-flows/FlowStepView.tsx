import type {
  ConversationItem,
  TurnContext,
} from "@posthog/ui/features/sessions/components/buildConversationItems";
import { SubagentToolView } from "@posthog/ui/features/sessions/components/session-update/SubagentToolView";
import type { ToolViewProps } from "@posthog/ui/features/sessions/components/session-update/toolCallUtils";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface FlowStepViewProps extends ToolViewProps {
  childItems: ConversationItem[];
  turnContext: TurnContext;
}

/**
 * A flow step: the native subagent card (title + live child tool calls) plus
 * the step's text — its streamed commentary while running, replaced by the
 * handoff when it finishes. SubagentToolView alone never shows card content,
 * which left handoffs invisible.
 */
export function FlowStepView(props: FlowStepViewProps) {
  const text = (props.toolCall.content ?? [])
    .flatMap((block) =>
      block.type === "content" && block.content.type === "text"
        ? [block.content.text]
        : [],
    )
    .join("\n")
    .trim();
  return (
    <div className="flex flex-col gap-1">
      <SubagentToolView {...props} defaultExpanded />
      {text ? (
        <div className="chat-markdown ml-6 max-w-3xl rounded-md border border-gray-4 bg-gray-1 px-3 py-2 text-[13px] text-gray-12">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
        </div>
      ) : null}
    </div>
  );
}
