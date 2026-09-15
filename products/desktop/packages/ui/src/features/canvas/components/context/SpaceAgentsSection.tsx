import {
  ArrowRightIcon,
  ChartLineUpIcon,
  RobotIcon,
  StrategyIcon,
} from "@phosphor-icons/react";
import { channelDisplayReference } from "@posthog/core/canvas/channelName";
import type { ContextDocument } from "@posthog/core/canvas/contextDocument";
import {
  Button,
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemMedia,
  ItemTitle,
  Text,
} from "@posthog/quill";
import { useLoopDraftStore } from "@posthog/ui/features/loops/loopDraftStore";
import {
  defaultLoopContextOutputs,
  type LoopTriggerDraft,
  nextDraftTriggerKey,
} from "@posthog/ui/features/loops/loopFormTypes";
import { systemTimezone } from "@posthog/ui/primitives/timezone";
import { navigateToNewLoop } from "@posthog/ui/router/navigationBridge";
import { SectionCard } from "./SectionCard";

interface SpaceAgentsSectionProps {
  channelId: string;
  channelName: string;
  doc: ContextDocument;
}

function scheduleDraft(cron: string): LoopTriggerDraft {
  return {
    key: nextDraftTriggerKey(),
    type: "schedule",
    enabled: true,
    config: { cron_expression: cron, timezone: systemTimezone() },
  };
}

interface AgentRecipe {
  id: string;
  title: string;
  description: string;
  icon: React.ReactNode;
  cron: string;
  name: string;
  instructions: (reference: string, doc: ContextDocument) => string;
}

const RECIPES: AgentRecipe[] = [
  {
    id: "goal-report",
    title: "Weekly goal report",
    description:
      "Every Monday: run each goal's measure, compare with its target, and post what moved and why.",
    icon: <ChartLineUpIcon size={18} />,
    cron: "0 9 * * 1",
    name: "Weekly goal report",
    instructions: (reference, doc) =>
      [
        `Read the context of ${reference}: the knowledge, the linked PostHog objects, and the goals.`,
        "For each goal, run its HogQL measure and compare the current value with the target.",
        "Then post a short report to the space feed with one line per goal: status (met, on track, behind), the current value against the target, what moved since last week, and the most likely reason.",
        doc.objects.length > 0
          ? "Use the linked dashboards, insights, flags, and experiments to explain the movement."
          : "If no PostHog objects are linked yet, suggest which insights would explain the movement.",
        "Keep it under 200 words. Flag anything that needs a decision.",
      ].join("\n"),
  },
  {
    id: "bets",
    title: "Bets to move the goals",
    description:
      "Every two weeks: propose three small bets most likely to move the goals, with how to measure each.",
    icon: <StrategyIcon size={18} />,
    cron: "0 10 1,15 * *",
    name: "Bets for the goals",
    instructions: (reference, doc) =>
      [
        `Read the context of ${reference}: the knowledge, the linked PostHog objects, and the goals.`,
        "Look at recent product data for this area: trends, funnels, replays, errors, and any running experiments.",
        "Propose three bets, each a small change or experiment most likely to move one of the goals.",
        "For each bet give: the hypothesis, the goal it targets and the expected effect, the effort (S/M/L), and the HogQL or insight that would show whether it worked.",
        doc.goals.length === 0
          ? "There are no goals yet. Start by proposing the two goals this space should track, with a HogQL measure for each, then propose bets against them."
          : "Rank the bets by expected effect per unit of effort.",
        "Post the list to the space feed.",
      ].join("\n"),
  },
];

/** Hands the context to a scheduled agent that reports on the goals and proposes bets. */
export function SpaceAgentsSection({
  channelId,
  channelName,
  doc,
}: SpaceAgentsSectionProps) {
  const reference = channelDisplayReference(channelName);

  const start = (recipe: AgentRecipe) => {
    useLoopDraftStore.getState().setPrefill({
      name: recipe.name,
      description: recipe.description,
      instructions: recipe.instructions(reference, doc),
      triggers: [scheduleDraft(recipe.cron)],
      contextTarget: {
        folderId: channelId,
        name: channelName,
        outputs: defaultLoopContextOutputs(),
      },
    });
    navigateToNewLoop();
  };

  return (
    <SectionCard
      icon={<RobotIcon size={16} />}
      title="Agents for this space"
      description="Scheduled agents that read this context, report on the goals, and propose bets."
      flush
    >
      <div className="grid @2xl:grid-cols-2 gap-3">
        {RECIPES.map((recipe) => (
          <Item
            key={recipe.id}
            variant="pressable"
            className="h-full items-start border-border bg-card"
            render={<button type="button" onClick={() => start(recipe)} />}
          >
            <ItemMedia variant="icon">{recipe.icon}</ItemMedia>
            <ItemContent className="min-w-0">
              <ItemTitle>{recipe.title}</ItemTitle>
              <ItemDescription className="text-xs">
                {recipe.description}
              </ItemDescription>
            </ItemContent>
            <ItemActions className="self-center">
              <ArrowRightIcon size={14} className="text-muted-foreground" />
            </ItemActions>
          </Item>
        ))}
      </div>
      <div className="mt-3 flex items-center justify-between gap-3">
        <Text size="xxs" variant="muted">
          {doc.goals.length === 0
            ? "Add a goal first so the agent has a number to report on."
            : "Each recipe opens a new loop with the prompt filled in. Change anything before you save it."}
        </Text>
        <Button
          variant="link-muted"
          size="xs"
          onClick={() => navigateToNewLoop()}
        >
          Start from a blank loop
        </Button>
      </div>
    </SectionCard>
  );
}
