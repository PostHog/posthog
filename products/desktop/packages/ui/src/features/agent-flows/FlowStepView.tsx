import type {
  ConversationItem,
  TurnContext,
} from "@posthog/ui/features/sessions/components/buildConversationItems";
import { SubagentToolView } from "@posthog/ui/features/sessions/components/session-update/SubagentToolView";
import type { ToolViewProps } from "@posthog/ui/features/sessions/components/session-update/toolCallUtils";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { FlowHandoffCard } from "./FlowHandoffCard";
import { readFlowHandoff } from "./useFlowHandoffArtifact";

interface FlowStepViewProps extends ToolViewProps {
  childItems: ConversationItem[];
  turnContext: TurnContext;
}

export function FlowStepView(props: FlowStepViewProps) {
  const text = (props.toolCall.content ?? [])
    .flatMap((block) =>
      block.type === "content" && block.content.type === "text"
        ? [block.content.text]
        : [],
    )
    .join("\n")
    .trim();
  const handoff = readFlowHandoff(props.toolCall.rawInput);
  const running = props.toolCall.status === "in_progress";
  return (
    <div className="flex flex-col gap-1">
      <SubagentToolView {...props} defaultExpanded />
      {handoff ? (
        <div className="ml-6">
          <FlowHandoffCard handoff={handoff} />
        </div>
      ) : running && text ? (
        <p className="ml-6 truncate text-[12px] text-gray-10">{text}</p>
      ) : text ? (
        <div className="chat-markdown ml-6 max-w-3xl rounded-md border border-gray-4 bg-gray-1 px-3 py-2 text-[13px] text-gray-12">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
        </div>
      ) : null}
    </div>
  );
}
