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
import { ScoutHelperSkillLinks } from "./ScoutHelperSkillLinks";

export function ScoutsEmptyState({ onNewAgent }: { onNewAgent: () => void }) {
  return (
    <Empty className="py-16">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <RobotIcon size={20} />
        </EmptyMedia>
        <EmptyTitle>No agents on this project yet</EmptyTitle>
        <EmptyDescription>
          Agents run on a schedule, watch one thing about your product, and send
          what they find to Self-driving. Describe the first one in a sentence
          and PostHog drafts it for you.
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button
          type="button"
          variant="primary"
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
