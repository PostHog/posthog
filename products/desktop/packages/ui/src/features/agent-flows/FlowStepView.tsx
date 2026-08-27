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
  const outcome = handoff ? (
    <FlowHandoffCard handoff={handoff} />
  ) : !running && text ? (
    <div className="chat-markdown max-w-3xl rounded-md border border-gray-4 bg-gray-1 px-3 py-2 text-[13px] text-gray-12">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  ) : undefined;

  return (
    <SubagentToolView
      {...props}
      defaultExpanded
      header={<span className="whitespace-nowrap">{props.toolCall.title}</span>}
      status={
        running && text ? (
          <span className="min-w-0 shrink truncate">{text}</span>
        ) : undefined
      }
      footer={outcome}
    />
  );
}
