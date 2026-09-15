import {
  ArrowSquareOutIcon,
  BookOpenTextIcon,
  ChatsCircleIcon,
  CodeIcon,
  LockSimpleIcon,
  SquaresFourIcon,
  UsersThreeIcon,
} from "@phosphor-icons/react";
import {
  Badge,
  Button,
  Card,
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
  Heading,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Text,
} from "@posthog/quill";
import type { OnboardingLandingDestination } from "@posthog/shared/analytics-events";
import { SpacesIcon } from "@posthog/ui/features/canvas/components/SpacesIcon";
import { type ReactNode, useState } from "react";
import {
  composerPreview,
  loopsPreview,
  selfDrivingPreview,
  slackPreview,
} from "./OnboardingPreviews";

type OpenDestination = (
  destination: OnboardingLandingDestination,
  href: string,
) => void;

interface StartAction {
  key: string;
  label: string;
  href: string;
  /** Reported destination when the action opens something other than its tab. */
  destination?: OnboardingLandingDestination;
  comingSoon?: boolean;
}

interface StartPath {
  destination: OnboardingLandingDestination;
  label: ReactNode;
  badge?: string;
  title: ReactNode;
  lead: string;
  facts: string[];
  actions: StartAction[];
  preview: ReactNode;
}

export interface TaskSpaceHrefs {
  general: string;
  personal: string;
}

const posthogMention = <span className="font-mono">@posthog</span>;

function buildStartPaths(
  taskSpaceHrefs: TaskSpaceHrefs,
  autoresearchAvailable: boolean,
): StartPath[] {
  return [
    {
      destination: "tasks",
      label: "You",
      title: "You describe a change",
      lead: "Write a brief in a new task and send it to an agent. Add context first if you want: files, constraints, and what done looks like.",
      facts: [
        "Works in your personal space or a team space",
        "The thread stays open, so you can reply to steer the agent mid-run",
        "Ask for a canvas instead of code if you want a doc or data view",
        ...(autoresearchAvailable
          ? [
              "Turn on autoresearch to have the agent improve a metric across attempts",
            ]
          : []),
      ],
      actions: [
        {
          key: "tasks-general",
          label: "Create task in general",
          href: taskSpaceHrefs.general,
        },
        {
          key: "tasks-personal",
          label: "Create task in personal",
          href: taskSpaceHrefs.personal,
        },
        ...(autoresearchAvailable
          ? [
              {
                key: "autoresearch",
                label: "Start autoresearch",
                href: `${taskSpaceHrefs.general}?mode=autoresearch`,
                destination: "autoresearch" as const,
              },
            ]
          : []),
      ],
      preview: composerPreview,
    },
    {
      destination: "self-driving",
      label: "Self-driving",
      title: "Desktop finds the problem",
      lead: "Self-driving watches error tracking, product analytics, and logs in your PostHog project and files prioritized problems in an inbox. Open one and it's already a task.",
      facts: [
        "Nothing runs until you choose to work on it",
        "Each item links back to the signal it came from",
        "Each report has the finding, its likely cause, and the evidence",
      ],
      actions: [{ key: "self-driving", label: "View inbox", href: "/inbox" }],
      preview: selfDrivingPreview,
    },
    {
      destination: "slack",
      label: <>{posthogMention} in Slack</>,
      title: <>You mention {posthogMention} in Slack</>,
      lead: "Tag @posthog in any thread. The thread so far becomes the brief, the agent runs in your team's space, and the result posts back to the thread.",
      facts: [
        "The bug report and the fix stay in one thread",
        "Replies in the thread go to the agent while it runs",
        "Reports and canvases link back, and code changes come with the PR",
      ],
      actions: [
        { key: "slack", label: "Connect Slack", href: "/settings/slack" },
      ],
      preview: slackPreview,
    },
    {
      destination: "loops",
      label: "Loops",
      badge: "Coming soon",
      title: "The same task, on a schedule",
      lead: "Run a task every morning, every deploy, or when an event fires. Each run starts from the latest context, so a weekly support ticket summary stays current.",
      facts: [
        "Runs on a schedule or an event trigger",
        "Results stack in the feed like any other session",
        "Pause or edit the brief at any time",
      ],
      actions: [
        {
          key: "loops",
          label: "Set up a loop",
          href: "/loops/new",
          comingSoon: true,
        },
      ],
      preview: loopsPreview,
    },
  ];
}

const results = [
  {
    title: "Code change",
    description:
      "Changed files, checks, and implementation notes. Open the PR from here.",
    icon: <CodeIcon size={16} />,
  },
  {
    title: "Canvas",
    description:
      "A shared doc, data view, or small tool. It lives in the space, and anyone can edit it.",
    icon: <SquaresFourIcon size={16} />,
  },
];

const spaceDetails = [
  {
    title: "Personal space",
    description: "Only you. Your sessions, canvases, and context.",
    icon: <LockSimpleIcon size={16} />,
  },
  {
    title: "Public space",
    description:
      "A team or area of work. Everyone in it can start and follow tasks.",
    icon: <UsersThreeIcon size={16} />,
  },
  {
    title: "Feed",
    description:
      "Every session in the space, newest first. Reply in any thread.",
    icon: <ChatsCircleIcon size={16} />,
  },
  {
    title: "Context",
    description:
      "The space's CONTEXT.md: conventions and key files that agents read when relevant.",
    icon: <BookOpenTextIcon size={16} />,
  },
];

interface StartActionButtonProps {
  action: StartAction;
  destination: OnboardingLandingDestination;
  primary: boolean;
  onOpenDestination: OpenDestination;
}

function StartActionButton({
  action,
  destination,
  primary,
  onOpenDestination,
}: StartActionButtonProps) {
  const variant = primary ? "primary" : "outline";
  const dataAttr = `onboarding-start-${action.key}`;

  if (action.comingSoon) {
    return (
      <div className="flex flex-col items-start gap-1">
        <Button variant={variant} disabled data-attr={dataAttr}>
          {action.label}
        </Button>
        <Text size="xxs" variant="muted" className="pl-2">
          Coming soon
        </Text>
      </div>
    );
  }

  return (
    <Button
      nativeButton={false}
      variant={variant}
      className="self-start"
      data-attr={dataAttr}
      render={
        // biome-ignore lint/a11y/useAnchorContent: Base UI adds the button text to this anchor.
        <a
          href={action.href}
          onClick={(event) => {
            event.preventDefault();
            onOpenDestination(action.destination ?? destination, action.href);
          }}
        />
      }
    >
      {action.label}
      <ArrowSquareOutIcon aria-hidden />
    </Button>
  );
}

export interface OnboardingLandingProps {
  selfDrivingAvailable: boolean;
  autoresearchAvailable: boolean;
  taskSpaceHrefs: TaskSpaceHrefs;
  onOpenDestination: OpenDestination;
}

const pageColumn = "mx-auto w-full max-w-5xl px-6";

export function OnboardingLanding({
  selfDrivingAvailable,
  autoresearchAvailable,
  taskSpaceHrefs,
  onOpenDestination,
}: OnboardingLandingProps) {
  const [activePath, setActivePath] =
    useState<OnboardingLandingDestination>("tasks");
  const startPaths = buildStartPaths(taskSpaceHrefs, autoresearchAvailable);
  const visiblePaths = selfDrivingAvailable
    ? startPaths
    : startPaths.filter((path) => path.destination !== "self-driving");

  return (
    <div className="@container h-full overflow-auto bg-gray-1">
      <header className={`${pageColumn} flex flex-col gap-1 pt-8 pb-5`}>
        <h1 className="font-bold text-xl">How work moves through Desktop</h1>
        <Text size="sm" variant="muted">
          Pick how a task starts. What happens after is always the same.
        </Text>
      </header>

      <Tabs
        value={activePath}
        onValueChange={(value: OnboardingLandingDestination) =>
          setActivePath(value)
        }
      >
        {/* The list overlaps the full-width rule by 1px so the active line sits on it, and the line
            is raised above the active tab's rounded background, which otherwise paints over its top half. */}
        <div className="border-border border-b">
          <div className={pageColumn}>
            <TabsList
              variant="line"
              aria-label="How work starts"
              className="-mb-px p-0 [&_.quill-tabs\_\_indicator]:z-2"
            >
              {visiblePaths.map((path) => (
                <TabsTrigger
                  key={path.destination}
                  value={path.destination}
                  data-attr={`onboarding-tab-${path.destination}`}
                >
                  {path.label}
                  {path.badge && <Badge>{path.badge}</Badge>}
                </TabsTrigger>
              ))}
            </TabsList>
          </div>
        </div>

        {visiblePaths.map((path) => (
          <TabsContent
            key={path.destination}
            value={path.destination}
            className={`${pageColumn} grid @4xl:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)] grid-cols-1 items-start gap-7 pt-6 pb-8`}
          >
            <div className="flex flex-col">
              <Heading size="sm" className="mb-1 font-bold">
                {path.title}
              </Heading>
              <Text size="sm" variant="muted" className="max-w-md text-[13px]">
                {path.lead}
              </Text>
              <ul className="mt-3 mb-4 flex flex-col gap-1 text-[13px]">
                {path.facts.map((fact) => (
                  <li key={fact} className="flex gap-2">
                    <span
                      className="mt-2 size-1.5 shrink-0 rounded-full bg-(--accent-9)"
                      aria-hidden
                    />
                    {fact}
                  </li>
                ))}
              </ul>
              <div className="flex flex-wrap gap-2">
                {path.actions.map((action, index) => (
                  <StartActionButton
                    key={action.key}
                    action={action}
                    destination={path.destination}
                    primary={index === 0}
                    onOpenDestination={onOpenDestination}
                  />
                ))}
              </div>
            </div>
            {path.preview}
          </TabsContent>
        ))}
      </Tabs>

      <main className={`${pageColumn} pb-8`}>
        <section className="mb-7">
          <div className="mb-3.5 flex flex-wrap items-baseline justify-between gap-3">
            <Heading size="sm" className="font-bold">
              Then you review the result
            </Heading>
            <Text size="sm" variant="muted">
              The same, whichever way it started
            </Text>
          </div>
          <Card className="grid @3xl:grid-cols-2 grid-cols-1 gap-0 overflow-hidden py-0">
            {results.map((result) => (
              <div
                key={result.title}
                className="flex flex-col gap-1.5 border-border @3xl:border-r border-b @3xl:border-b-0 px-4 py-3.5 @3xl:last:border-r-0 last:border-b-0"
              >
                <h3 className="flex items-center gap-2 font-bold text-[13px]">
                  <span className="text-muted-foreground" aria-hidden>
                    {result.icon}
                  </span>
                  {result.title}
                </h3>
                <Text size="sm" variant="muted" className="text-[13px]">
                  {result.description}
                </Text>
              </div>
            ))}
          </Card>
        </section>

        <Collapsible className="overflow-hidden rounded-(--radius-2) border border-border bg-card">
          <CollapsibleTrigger
            data-attr="onboarding-spaces"
            className="flex h-auto w-full items-center gap-2 px-4 py-3 text-left text-sm hover:bg-fill-hover aria-expanded:bg-fill-hover"
          >
            <SpacesIcon size={16} />
            Where all of this lives: spaces
          </CollapsibleTrigger>
          <CollapsibleContent className="border-border border-t">
            <div className="grid @3xl:grid-cols-4 grid-cols-1 gap-px bg-border">
              {spaceDetails.map((detail) => (
                <div key={detail.title} className="flex gap-2.5 bg-card p-3.5">
                  <span
                    className="mt-0.5 shrink-0 text-muted-foreground"
                    aria-hidden
                  >
                    {detail.icon}
                  </span>
                  <div className="min-w-0">
                    <h3 className="font-bold text-[13px]">{detail.title}</h3>
                    <Text size="sm" variant="muted" className="text-[13px]">
                      {detail.description}
                    </Text>
                  </div>
                </div>
              ))}
            </div>
          </CollapsibleContent>
        </Collapsible>
      </main>
    </div>
  );
}
