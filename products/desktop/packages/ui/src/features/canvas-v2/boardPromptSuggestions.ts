import {
  ArrowsClockwise,
  ChartLine,
  FunnelSimple,
  ListChecks,
  NumberCircleOne,
  Table,
} from "@phosphor-icons/react";
import type { SuggestedPrompt } from "@posthog/ui/features/task-detail/components/SuggestedPromptCard";

export const BOARD_PROMPT_SUGGESTIONS: SuggestedPrompt[] = [
  {
    label: "Product health",
    description: "Signups, activation, retention",
    icon: NumberCircleOne,
    color: "blue",
    prompt:
      "Add a row of single-number fragments to this board for signups, activation, and retention over the last 30 days, each with the change against the period before.",
  },
  {
    label: "Active people per day",
    description: "A trend for the last 30 days",
    icon: ChartLine,
    color: "violet",
    prompt:
      "Add a trend chart of active people per day for the last 30 days, and a short note under it that says what the trend does.",
  },
  {
    label: "Signup to activation",
    description: "A funnel with each drop-off",
    icon: FunnelSimple,
    color: "green",
    prompt:
      "Add a funnel fragment from signup to activation, with the conversion rate at each step and the largest drop-off called out.",
  },
  {
    label: "Top pages",
    description: "The pages with the most views",
    icon: Table,
    color: "amber",
    prompt:
      "Add a HogQL table of the ten pages with the most views in the last 7 days, with views and unique people per page.",
  },
  {
    label: "Retention cohorts",
    description: "How weekly cohorts come back",
    icon: ArrowsClockwise,
    color: "purple",
    prompt:
      "Add a retention fragment that shows how each weekly cohort of new people comes back, and note which cohort holds up best.",
  },
  {
    label: "Weekly review",
    description: "A checklist and notes",
    icon: ListChecks,
    color: "teal",
    prompt:
      "Set this board up for a weekly review: a heading, a checklist of things to look at, and a markdown notes fragment to write findings in.",
  },
];
