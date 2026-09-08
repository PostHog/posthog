import {
  ArrowRightIcon,
  ArrowSquareOutIcon,
  BookOpenTextIcon,
  ChatsCircleIcon,
  CheckCircleIcon,
  ListChecksIcon,
  LockSimpleIcon,
  RobotIcon,
  SquaresFourIcon,
  TrayIcon,
  UsersThreeIcon,
} from "@phosphor-icons/react";
import {
  Card,
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
  Text,
} from "@posthog/quill";
import type { OnboardingLandingDestination } from "@posthog/shared/analytics-events";
import { SpacesIcon } from "@posthog/ui/features/canvas/components/SpacesIcon";
import { Fragment, type ReactNode } from "react";
import { OnboardingConceptPreview } from "./OnboardingConceptPreview";

interface OnboardingGuidedLayoutProps {
  selfDrivingAvailable: boolean;
  onOpenDestination: (
    destination: OnboardingLandingDestination,
    href: string,
  ) => void;
}

interface WorkflowStep {
  number: number;
  title: string;
  description: string;
  icon: ReactNode;
  destination?: OnboardingLandingDestination;
  href?: string;
}

const workflowSteps: WorkflowStep[] = [
  {
    number: 1,
    title: "Spaces",
    description: "Keep related work and people together.",
    icon: <SpacesIcon size={16} />,
    destination: "spaces",
    href: "/spaces",
  },
  {
    number: 2,
    title: "Tasks",
    description: "Give an agent a code change.",
    icon: <ListChecksIcon size={16} />,
    destination: "tasks",
    href: "/new",
  },
  {
    number: 3,
    title: "Agents",
    description: "The agent works through the task.",
    icon: <RobotIcon size={16} />,
    destination: "agents",
    href: "/agents",
  },
  {
    number: 4,
    title: "Results",
    description: "Review the result and next steps.",
    icon: <CheckCircleIcon size={16} />,
  },
];

const spaceDetails = [
  {
    title: "Personal",
    description: "Private work",
    icon: <LockSimpleIcon size={16} />,
  },
  {
    title: "Public",
    description: "Shared team work",
    icon: <UsersThreeIcon size={16} />,
  },
  {
    title: "Feed",
    description: "Sessions and replies",
    icon: <ChatsCircleIcon size={16} />,
  },
  {
    title: "Context",
    description: "Shared agent background",
    icon: <BookOpenTextIcon size={16} />,
  },
] as const;

const interactiveCardClassName =
  "transition-[background-color,border-color,transform] duration-150 hover:border-(--accent-8) hover:bg-fill-hover active:scale-[0.98] motion-reduce:transform-none motion-reduce:transition-none";

export function OnboardingGuidedLayout({
  selfDrivingAvailable,
  onOpenDestination,
}: OnboardingGuidedLayoutProps) {
  const exploreItems = [
    ...(selfDrivingAvailable
      ? [
          {
            destination: "self-driving" as const,
            title: "Self-driving",
            description:
              "Review reports that PostHog creates from activity in your project.",
            href: "/inbox",
            icon: <TrayIcon size={17} />,
          },
        ]
      : []),
    {
      destination: "canvases" as const,
      title: "Canvases",
      description: "Build shared documents, data views, and small tools.",
      href: "/canvases",
      icon: <SquaresFourIcon size={17} />,
    },
  ];

  return (
    <div data-attr="onboarding-guided-layout">
      <div className="mb-5 flex max-w-2xl flex-col gap-1.5">
        <h1 className="font-bold text-xl">Get to know PostHog Desktop</h1>
        <Text className="text-gray-11">
          Learn how work moves from an idea to a completed result.
        </Text>
      </div>

      <a
        href="/new"
        aria-label="Create your first task in a new tab"
        data-attr="onboarding-guided-start-task"
        className={`mb-6 flex items-center gap-4 rounded-(--radius-2) border border-(--accent-7) bg-(--accent-a2) px-5 py-4 text-foreground no-underline ${interactiveCardClassName}`}
        onClick={(event) => {
          event.preventDefault();
          onOpenDestination("tasks", "/new");
        }}
      >
        <span className="flex size-9 shrink-0 items-center justify-center rounded-(--radius-2) bg-(--accent-a3) text-(--accent-11)">
          <ListChecksIcon size={19} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block font-semibold text-base">
            Start here: Create your first task
          </span>
          <span className="mt-1 block text-gray-11 text-sm">
            Describe a change, follow its progress, and review it.
          </span>
        </span>
        <ArrowSquareOutIcon size={17} className="shrink-0 text-gray-11" />
      </a>

      <section className="mb-6">
        <h2 className="mb-3 font-semibold text-base">How Desktop works</h2>
        <div className="grid @4xl:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr] grid-cols-1 items-stretch gap-2">
          {workflowSteps.map((step, index) => {
            const destination = step.destination;
            const href = step.href;
            const content = (
              <>
                <span className="flex items-center gap-2">
                  <span className="flex size-5 items-center justify-center rounded-full bg-gray-4 font-semibold text-[11px] text-gray-12">
                    {step.number}
                  </span>
                  <span className="text-gray-11">{step.icon}</span>
                  <span className="font-semibold text-sm">{step.title}</span>
                  {destination && (
                    <ArrowSquareOutIcon
                      size={12}
                      className="ml-auto shrink-0 text-gray-10"
                    />
                  )}
                </span>
                <span className="mt-2 block text-gray-11 text-xs leading-4">
                  {step.description}
                </span>
              </>
            );

            return (
              <Fragment key={step.title}>
                {destination && href ? (
                  <a
                    href={href}
                    aria-label={`Open ${step.title} in a new tab`}
                    data-attr={`onboarding-guided-open-${destination}`}
                    className={`rounded-(--radius-2) border border-border bg-card p-3 text-foreground no-underline ${interactiveCardClassName}`}
                    onClick={(event) => {
                      event.preventDefault();
                      onOpenDestination(destination, href);
                    }}
                  >
                    {content}
                  </a>
                ) : (
                  <div className="rounded-(--radius-2) border border-border bg-card p-3 text-foreground">
                    {content}
                  </div>
                )}
                {index < workflowSteps.length - 1 && (
                  <ArrowRightIcon
                    size={14}
                    className="@4xl:rotate-0 rotate-90 place-self-center text-gray-9"
                    aria-hidden
                  />
                )}
              </Fragment>
            );
          })}
        </div>
      </section>

      <section className="mb-6">
        <h2 className="mb-3 font-semibold text-base">Explore more</h2>
        <div className="grid @3xl:grid-cols-2 grid-cols-1 gap-4">
          {exploreItems.map((item) => (
            <Card key={item.destination} className="overflow-hidden py-0">
              <a
                href={item.href}
                aria-label={`Open ${item.title} in a new tab`}
                data-attr={`onboarding-guided-open-${item.destination}`}
                className={`block h-full text-foreground no-underline ${interactiveCardClassName}`}
                onClick={(event) => {
                  event.preventDefault();
                  onOpenDestination(item.destination, item.href);
                }}
              >
                <OnboardingConceptPreview
                  destination={item.destination}
                  placement="top"
                />
                <span className="flex items-start gap-3 p-4">
                  <span className="mt-0.5 shrink-0 text-gray-11">
                    {item.icon}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block font-semibold text-sm">
                      {item.title}
                    </span>
                    <span className="mt-1 block max-w-sm text-gray-11 text-sm">
                      {item.description}
                    </span>
                  </span>
                  <ArrowSquareOutIcon
                    size={15}
                    className="mt-0.5 shrink-0 text-gray-11"
                  />
                </span>
              </a>
            </Card>
          ))}
        </div>
      </section>

      <Collapsible className="overflow-hidden rounded-(--radius-2) border border-border bg-card">
        <CollapsibleTrigger
          data-attr="onboarding-guided-inside-space"
          className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-fill-hover aria-expanded:bg-fill-hover"
        >
          <span className="flex items-center gap-2 font-semibold text-sm">
            <SpacesIcon size={16} />
            Inside a space
          </span>
        </CollapsibleTrigger>
        <CollapsibleContent className="border-border border-t">
          <div className="grid @3xl:grid-cols-4 grid-cols-2 gap-px bg-border">
            {spaceDetails.map((detail) => (
              <div
                key={detail.title}
                className="flex items-center gap-2 bg-card p-3"
              >
                <span className="shrink-0 text-gray-10">{detail.icon}</span>
                <span className="min-w-0">
                  <span className="block font-medium text-sm">
                    {detail.title}
                  </span>
                  <span className="block truncate text-gray-11 text-xs">
                    {detail.description}
                  </span>
                </span>
              </div>
            ))}
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}
