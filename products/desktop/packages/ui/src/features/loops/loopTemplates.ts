import {
  Bug,
  ChartLine,
  ChatCircleText,
  GitPullRequest,
  type Icon,
  Lifebuoy,
  ListChecks,
  NotePencil,
  Package,
  Sun,
  TestTube,
  Warning,
} from "@phosphor-icons/react";
import type { LoopSchemas } from "@posthog/api-client/loops";
import { systemTimezone } from "@posthog/ui/primitives/timezone";
import {
  type LoopFormValues,
  type LoopTriggerDraft,
  nextDraftTriggerKey,
} from "./loopFormTypes";

export type LoopTemplateCategory = "engineering" | "operations";

export const LOOP_TEMPLATE_CATEGORIES: {
  value: LoopTemplateCategory;
  label: string;
}[] = [
  { value: "engineering", label: "Engineering" },
  { value: "operations", label: "Operations" },
];

export interface LoopTemplate {
  id: string;
  category: LoopTemplateCategory;
  icon: Icon;
  name: string;
  description: string;
  /** Short, human phrase describing the trigger, shown on the card. */
  triggerLabel: string;
  /** Integrations and surfaces the template works with, shown on the card. */
  worksWith: string[];
  /** Accent tone for the card's icon tile. */
  tone: "blue" | "red" | "purple" | "teal" | "amber" | "green";
  build: () => Partial<LoopFormValues>;
}

function scheduleDraft(cron: string): LoopTriggerDraft {
  return {
    key: nextDraftTriggerKey(),
    type: "schedule",
    enabled: true,
    config: { cron_expression: cron, timezone: systemTimezone() },
  };
}

function githubDraft(
  events: LoopSchemas.LoopGithubTriggerEventEnum[],
): LoopTriggerDraft {
  return {
    key: nextDraftTriggerKey(),
    type: "github",
    enabled: true,
    config: { github_integration_id: 0, repository: "", events },
  };
}

export const LOOP_TEMPLATES: LoopTemplate[] = [
  {
    id: "pr-review-digest",
    category: "engineering",
    icon: GitPullRequest,
    name: "PR review digest",
    description:
      "Summarize open pull requests, their review and CI status, and what needs attention.",
    triggerLabel: "Runs weekdays at 11:00",
    worksWith: ["GitHub", "Slack"],
    tone: "blue",
    build: () => ({
      name: "PR review digest",
      instructions:
        "Summarize the open pull requests in this repository. For each, note its review status, CI status, and how long it has been waiting. Call out anything that needs attention, then post the summary to the team.",
      triggers: [scheduleDraft("0 11 * * 1-5")],
    }),
  },
  {
    id: "ci-failure-summary",
    category: "engineering",
    icon: Bug,
    name: "CI failure summary",
    description:
      "Digest the failing CI runs from the last day and post a summary to your team channel.",
    triggerLabel: "Runs daily at 9:00",
    worksWith: ["GitHub", "Slack"],
    tone: "red",
    build: () => ({
      name: "CI failure summary",
      instructions:
        "Review the CI runs from the last 24 hours. Summarize which jobs failed, the likely cause of each, and any patterns across runs. Post the summary to the team channel.",
      triggers: [scheduleDraft("0 9 * * *")],
    }),
  },
  {
    id: "flaky-test-tracker",
    category: "engineering",
    icon: TestTube,
    name: "Flaky test tracker",
    description:
      "Find tests that pass and fail intermittently across recent CI runs, and open an issue.",
    triggerLabel: "Runs Mondays at 9:00",
    worksWith: ["GitHub"],
    tone: "purple",
    build: () => ({
      name: "Flaky test tracker",
      instructions:
        "Look through recent CI runs and identify tests that pass and fail intermittently on unchanged code. List the flakiest tests with links to failing runs, and open an issue tracking them.",
      triggers: [scheduleDraft("0 9 * * 1")],
    }),
  },
  {
    id: "dependency-update-check",
    category: "engineering",
    icon: Package,
    name: "Dependency update check",
    description:
      "Scan for outdated packages, security patches, and breaking changes, then open a PR.",
    triggerLabel: "Runs Mondays at 11:30",
    worksWith: ["GitHub"],
    tone: "teal",
    build: () => ({
      name: "Dependency update check",
      instructions:
        "Check this repository's dependencies for outdated versions, security advisories, and breaking changes. Open a pull request that bumps the safe updates and summarize anything that needs manual review.",
      triggers: [scheduleDraft("30 11 * * 1")],
    }),
  },
  {
    id: "release-notes-drafter",
    category: "engineering",
    icon: NotePencil,
    name: "Release notes drafter",
    description:
      "Draft user-facing release notes each time a pull request merges to the main branch.",
    triggerLabel: "Triggered when a PR merges",
    worksWith: ["GitHub"],
    tone: "amber",
    build: () => ({
      name: "Release notes drafter",
      instructions:
        "When a pull request merges to the main branch, draft a user-facing release note for the change: what changed, why it matters, and any migration steps. Keep the tone plain and concrete.",
      triggers: [githubDraft(["pull_request"])],
    }),
  },
  {
    id: "issue-triage",
    category: "engineering",
    icon: ListChecks,
    name: "Issue triage",
    description:
      "Review new issues, categorize bugs and feature requests, and flag likely duplicates.",
    triggerLabel: "Triggered by new issues",
    worksWith: ["GitHub"],
    tone: "green",
    build: () => ({
      name: "Issue triage",
      instructions:
        "When a new issue is opened, categorize it (bug, feature request, question, or docs), assess its severity, and check whether it duplicates an existing issue. Apply the right labels and comment with your reasoning.",
      triggers: [githubDraft(["issues"])],
    }),
  },
  {
    id: "standup-summary",
    category: "operations",
    icon: Sun,
    name: "Standup summary",
    description:
      "Post a morning summary of what the team shipped yesterday and what's in progress.",
    triggerLabel: "Runs weekdays at 9:00",
    worksWith: ["GitHub", "Slack"],
    tone: "amber",
    build: () => ({
      name: "Standup summary",
      instructions:
        "Summarize what the team shipped yesterday (merged PRs, closed issues) and what is currently in progress. Keep it short and skimmable, then post it to the standup channel.",
      triggers: [scheduleDraft("0 9 * * 1-5")],
    }),
  },
  {
    id: "weekly-review",
    category: "operations",
    icon: ChartLine,
    name: "Weekly review",
    description:
      "A Friday summary of the week's shipped work and what's carrying into next week.",
    triggerLabel: "Runs Fridays at 16:00",
    worksWith: ["GitHub", "Slack"],
    tone: "blue",
    build: () => ({
      name: "Weekly review",
      instructions:
        "Write a review of the week: the PRs merged, issues closed, and notable changes, plus what is still open and carrying into next week. Post it to the team channel.",
      triggers: [scheduleDraft("0 16 * * 5")],
    }),
  },
  {
    id: "support-ticket-triage",
    category: "operations",
    icon: Lifebuoy,
    name: "Support ticket triage",
    description:
      "Triage new support tickets: categorize, set priority, and draft a reply for approval.",
    triggerLabel: "Runs every hour",
    worksWith: ["Linear", "Slack"],
    tone: "teal",
    build: () => ({
      name: "Support ticket triage",
      instructions:
        "Review support tickets opened since the last run. Categorize each, set a priority, link any related issue, and draft a reply for a human to approve before it's sent.",
      triggers: [scheduleDraft("0 * * * *")],
    }),
  },
  {
    id: "incident-digest",
    category: "operations",
    icon: Warning,
    name: "Incident digest",
    description:
      "Summarize open incidents and alerts and their current status each morning.",
    triggerLabel: "Runs daily at 8:00",
    worksWith: ["Sentry", "Slack"],
    tone: "red",
    build: () => ({
      name: "Incident digest",
      instructions:
        "Summarize the open incidents and active alerts, their severity, and current status. Flag anything that has been open too long, then post the digest to the on-call channel.",
      triggers: [scheduleDraft("0 8 * * *")],
    }),
  },
  {
    id: "metrics-digest",
    category: "operations",
    icon: ChartLine,
    name: "Metrics digest",
    description:
      "Summarize key product metrics week over week and flag notable changes.",
    triggerLabel: "Runs Mondays at 9:00",
    worksWith: ["PostHog", "Slack"],
    tone: "purple",
    build: () => ({
      name: "Metrics digest",
      instructions:
        "Pull the key product metrics for the last week, compare them to the prior week, and call out anything that moved notably. Post a short digest to the team channel.",
      triggers: [scheduleDraft("0 9 * * 1")],
    }),
  },
  {
    id: "changelog-drafter",
    category: "operations",
    icon: ChatCircleText,
    name: "Changelog drafter",
    description:
      "Draft a weekly customer-facing changelog from the changes that shipped.",
    triggerLabel: "Runs Fridays at 15:00",
    worksWith: ["GitHub"],
    tone: "green",
    build: () => ({
      name: "Changelog drafter",
      instructions:
        "From the pull requests merged this week, draft a customer-facing changelog: group related changes, write plain-language entries, and leave anything internal out. Save it as a draft for review.",
      triggers: [scheduleDraft("0 15 * * 5")],
    }),
  },
];
