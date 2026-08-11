import { ArrowLeftIcon } from "@phosphor-icons/react";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { Badge } from "@posthog/ui/primitives/Badge";
import { Flex, Text } from "@radix-ui/themes";
import { Link } from "@tanstack/react-router";
import { useMemo } from "react";
import { AgentBuilderHeaderControls } from "../agent-builder/AgentBuilderHeaderControls";
import { useSetAgentBuilderPage } from "../agent-builder/useSetAgentBuilderPage";
import { useAgentApplicationSession } from "../hooks/useAgentApplicationSession";
import { sessionStateColor } from "../utils/format";
import { AgentSessionDetailBody } from "./AgentSessionDetailBody";
import { CopyButton } from "./CopyButton";

/**
 * Full-screen session view: page chrome (back link + title) wrapping the shared
 * {@link AgentSessionDetailBody} (KPI strip + Conversation/Logs tabs). The body
 * renders the transcript read-only through code's native `ConversationView`.
 */
export function AgentSessionTranscriptView({
  idOrSlug,
  sessionId,
}: {
  idOrSlug: string;
  sessionId: string;
}) {
  const { data: session } = useAgentApplicationSession(idOrSlug, sessionId);
  const headerContent = useMemo(
    () => (
      <Text className="truncate whitespace-nowrap font-medium text-[13px]">
        Session
      </Text>
    ),
    [],
  );
  useSetHeaderContent(headerContent);
  const pageContext = {
    kind: "agent-session" as const,
    slug: idOrSlug,
    sessionId,
  };
  useSetAgentBuilderPage(pageContext);

  return (
    <Flex direction="column" className="h-full min-h-0">
      <Flex
        direction="column"
        gap="3"
        className="relative shrink-0 cursor-default select-none px-6 pt-5"
      >
        <AgentBuilderHeaderControls />
        <Link
          to="/code/agents/applications/$idOrSlug/sessions"
          params={{ idOrSlug }}
          className="flex w-fit items-center gap-1.5 text-[12px] text-gray-11 no-underline hover:text-gray-12"
        >
          <ArrowLeftIcon size={13} />
          Sessions
        </Link>
        <Flex align="center" gap="2" wrap="wrap" className="pr-44">
          <Text className="font-bold text-[22px] text-gray-12 leading-tight tracking-tight">
            Session
          </Text>
          <Flex
            align="center"
            gap="1"
            className="rounded-(--radius-1) border border-border bg-(--gray-2) py-0.5 pr-0.5 pl-2 text-[12px] text-gray-10"
          >
            <span className="font-mono" title="Session id">
              {sessionId}
            </span>
            <CopyButton text={sessionId} label="Copy session id" bare />
          </Flex>
          {session ? (
            <Badge color={sessionStateColor(session.state)}>
              {session.state}
            </Badge>
          ) : null}
        </Flex>
      </Flex>
      <div className="min-h-0 flex-1">
        <AgentSessionDetailBody
          idOrSlug={idOrSlug}
          sessionId={sessionId}
          showStateBadge={false}
        />
      </div>
    </Flex>
  );
}
