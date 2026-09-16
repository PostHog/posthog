import {
  Bug,
  ChartLine,
  ChatCircleText,
  Cube,
  CurrencyDollar,
  Flask,
  SquaresFour,
  Wrench,
} from "@phosphor-icons/react";
import type { SuggestedPrompt } from "@posthog/ui/features/task-detail/components/SuggestedPromptCard";

// Starter prompts shown as cards on the channels (project-bluebird) new-task
// screen. Clicking a card drops its `prompt` into the composer, ready to
// edit/send. Each prompt ends with a "User input:" block of fill-in lines the
// user completes before sending. Channels-only — the /code new-task screen
// keeps its discovery suggestions. Card styling mirrors SuggestedTaskCard
// (icon badge + title + description); the icon/color follow the same
// `var(--<color>-N)` token scheme.
//
// The research prompts end by asking for a canvas, so the answer is a surface
// the user can keep and share instead of chat history.
export const CHANNEL_TASK_SUGGESTIONS: SuggestedPrompt[] = [
  {
    label: "Debug a user issue",
    description: "Trace a specific user's events, replays, and errors",
    icon: Bug,
    color: "red",
    mode: "auto",
    prompt:
      "Help me debug an issue a specific user is hitting. Pull their recent events, session replays, and errors, then figure out what went wrong. Build a canvas that explains what you found and the evidence behind it.\n\n\nUser input:\n- Describe the user issue:\n- User identifier (distinct ID, email address, etc):",
  },
  {
    label: "Run a feature analysis",
    description: "Adoption, engagement, and retention of a feature",
    icon: ChartLine,
    color: "blue",
    mode: "auto",
    prompt:
      "Analyze how a feature is performing — adoption, engagement, and retention of users who use it vs. those who don't. Build a canvas that explains what you found, with the charts behind it.\n\n\nUser input:\n- Feature to analyze:\n- Time period (optional):",
  },
  {
    label: "Understand revenue patterns",
    description: "Trends over time, by plan, and by cohort",
    icon: CurrencyDollar,
    color: "green",
    mode: "auto",
    prompt:
      "Analyze our revenue trends — break it down over time, by plan, and by cohort, and call out notable changes and likely drivers. Build a canvas that explains what you found, with the charts behind it.\n\n\nUser input:\n- What revenue question are you trying to answer:\n- Time period (optional):",
  },
  {
    label: "Build a canvas",
    description: "Research a question and explain the answer",
    icon: SquaresFour,
    color: "violet",
    mode: "auto",
    prompt:
      "Research a question about our product, then build a canvas that explains the answer. Include the charts that show it and short written context for what they mean.\n\n\nUser input:\n- What should the canvas explain:\n- Time period (optional):",
  },
  {
    label: "Summarize user & agent feedback",
    description: "Common themes across recent feedback",
    icon: ChatCircleText,
    color: "amber",
    mode: "auto",
    prompt:
      "Summarize recent user and support/agent feedback — surface the common themes, complaints, and requests. Build a canvas that explains the themes, with examples behind each one.\n\n\nUser input:\n- Feedback source or topic to focus on:\n- Time period (optional):",
  },
  {
    label: "Interpret experiment results",
    description: "Significance and what to do next",
    icon: Flask,
    color: "purple",
    mode: "auto",
    prompt:
      "Interpret the results of an experiment — explain what the metrics show, whether it's significant, and what to do next. Build a canvas that explains the result and your recommendation.\n\n\nUser input:\n- Experiment name or key:\n- What decision are you trying to make (optional):",
  },
  {
    label: "Fix a bug",
    description: "Track down and fix a problem in the code",
    icon: Wrench,
    color: "orange",
    mode: "plan",
    prompt:
      "Help me fix a bug — track down the root cause in the code and implement a fix. Open a PR if appropriate.\n\n\nUser input:\n- Describe the bug / what's going wrong:\n- Steps to reproduce (optional):\n- Where it happens (file, page, area — optional):",
  },
  {
    label: "Build a new feature",
    description: "Design and implement something new",
    icon: Cube,
    color: "teal",
    mode: "plan",
    prompt:
      "Help me build a new feature — propose an approach, then implement it. Open a PR if appropriate.\n\n\nUser input:\n- Describe the feature you want:\n- Any constraints or requirements (optional):",
  },
];
