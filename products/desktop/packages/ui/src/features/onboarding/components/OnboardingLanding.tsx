import {
  ListChecksIcon,
  RobotIcon,
  SquaresFourIcon,
  TrayIcon,
  UsersThreeIcon,
} from "@phosphor-icons/react";
import { Button, Card, CardContent, Text } from "@posthog/quill";
import type { OnboardingLandingDestination } from "@posthog/shared/analytics-events";
import { SpacesIcon } from "@posthog/ui/features/canvas/components/SpacesIcon";
import type { ReactNode } from "react";

type OnboardingHref = "/spaces" | "/inbox" | "/canvases" | "/agents" | "/new";

interface OnboardingConcept {
  destination: OnboardingLandingDestination;
  title: string;
  description: string;
  buttonLabel: string;
  href: OnboardingHref;
  icon: ReactNode;
}

const concepts: OnboardingConcept[] = [
  {
    destination: "spaces",
    title: "Spaces",
    description:
      "Organize related work, context, and people in one shared place.",
    buttonLabel: "Open spaces",
    href: "/spaces",
    icon: <SpacesIcon size={18} />,
  },
  {
    destination: "multiplayer",
    title: "Multiplayer",
    description: "Work with your team in shared feeds, tasks, and canvases.",
    buttonLabel: "Open multiplayer",
    href: "/spaces",
    icon: <UsersThreeIcon size={18} />,
  },
  {
    destination: "self-driving",
    title: "Self-driving",
    description:
      "Review reports that PostHog creates from activity in your project.",
    buttonLabel: "Open self-driving",
    href: "/inbox",
    icon: <TrayIcon size={18} />,
  },
  {
    destination: "canvases",
    title: "Canvases",
    description: "Build shared documents, data views, and small tools.",
    buttonLabel: "Open canvases",
    href: "/canvases",
    icon: <SquaresFourIcon size={18} />,
  },
  {
    destination: "agents",
    title: "Agents",
    description: "Configure the agents and scouts that work for your team.",
    buttonLabel: "Open agents",
    href: "/agents",
    icon: <RobotIcon size={18} />,
  },
  {
    destination: "tasks",
    title: "Tasks",
    description: "Describe a code change and let the agent prepare it.",
    buttonLabel: "Open tasks",
    href: "/new",
    icon: <ListChecksIcon size={18} />,
  },
];

export interface OnboardingLandingProps {
  selfDrivingAvailable: boolean;
  onOpenDestination: (
    destination: OnboardingLandingDestination,
    href: string,
  ) => void;
}

export function OnboardingLanding({
  selfDrivingAvailable,
  onOpenDestination,
}: OnboardingLandingProps) {
  const visibleConcepts = selfDrivingAvailable
    ? concepts
    : concepts.filter((concept) => concept.destination !== "self-driving");

  return (
    <div className="h-full overflow-auto bg-gray-1">
      <main className="@container mx-auto w-full max-w-5xl px-6 py-8">
        <div className="mb-6 flex max-w-2xl flex-col gap-2">
          <h1 className="font-semibold text-xl">Get to know PostHog Desktop</h1>
          <Text variant="muted">
            Choose a concept to learn more. Each link opens in a new tab.
          </Text>
        </div>

        <div className="grid @3xl:grid-cols-2 grid-cols-1 gap-4">
          {visibleConcepts.map((concept) => (
            <Card key={concept.destination} className="h-full">
              <CardContent className="flex h-full flex-col gap-3 p-4">
                <div className="flex items-center gap-2 text-foreground">
                  <span className="flex shrink-0 items-center" aria-hidden>
                    {concept.icon}
                  </span>
                  <h2 className="font-semibold text-base">{concept.title}</h2>
                </div>
                <Text size="sm" variant="muted" className="flex-1">
                  {concept.description}
                </Text>
                <Button
                  nativeButton={false}
                  variant="outline"
                  className="self-start"
                  data-attr={`onboarding-open-${concept.destination}`}
                  render={
                    // biome-ignore lint/a11y/useAnchorContent: Base UI adds the button text to this anchor.
                    <a
                      href={concept.href}
                      aria-label={concept.buttonLabel}
                      onClick={(event) => {
                        event.preventDefault();
                        onOpenDestination(concept.destination, concept.href);
                      }}
                    />
                  }
                >
                  {concept.buttonLabel}
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      </main>
    </div>
  );
}
