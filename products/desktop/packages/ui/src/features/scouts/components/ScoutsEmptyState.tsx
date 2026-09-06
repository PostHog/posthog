import { PlusIcon, RobotIcon } from "@phosphor-icons/react";
import {
  Button,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { useAgentsPageActions } from "@posthog/ui/features/agents/agentsPageStore";
import { useSelfDrivingSetupStatus } from "@posthog/ui/features/inbox/hooks/useSelfDrivingSetupStatus";
import { ScoutHelperSkillLinks } from "./ScoutHelperSkillLinks";

export function ScoutsEmptyState({ onNewAgent }: { onNewAgent: () => void }) {
  const { showTab } = useAgentsPageActions();
  const { isLoading, isConfigured } = useSelfDrivingSetupStatus();

  // An empty fleet has two causes, and they need different first moves. With
  // nothing watching at all, sources come first: they are what Self-driving
  // reads, and one switch starts them. With sources already on, the only thing
  // missing is an agent.
  const needsSources = !isLoading && !isConfigured;

  return (
    <Empty className="py-16">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <RobotIcon size={20} />
        </EmptyMedia>
        <EmptyTitle>
          {needsSources
            ? "Nothing is watching this project yet"
            : "No agents on this project yet"}
        </EmptyTitle>
        <EmptyDescription>
          {needsSources
            ? "Self-driving reads your sources: error tracking, support, your issue tracker. Turn those on first, then add agents for what the sources miss."
            : "Agents run on a schedule, watch one thing about your product, and send what they find to Self-driving. Describe the first one in a sentence and PostHog drafts it for you."}
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        {needsSources ? (
          <Button
            type="button"
            variant="primary"
            size="default"
            onClick={() => showTab("setup")}
            data-attr="agents-empty-open-setup"
          >
            Turn on sources
          </Button>
        ) : null}
        <Button
          type="button"
          variant={needsSources ? "outline" : "primary"}
          size="default"
          onClick={onNewAgent}
          data-attr="agents-empty-new-agent"
        >
          <PlusIcon size={13} weight="bold" />
          New agent
        </Button>
        <ScoutHelperSkillLinks surface="empty_state" />
      </EmptyContent>
    </Empty>
  );
}
