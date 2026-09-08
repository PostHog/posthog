import {
  BookOpenTextIcon,
  ChatsCircleIcon,
  ListChecksIcon,
  LockSimpleIcon,
  RobotIcon,
  SquaresFourIcon,
  TrayIcon,
  UsersThreeIcon,
} from "@phosphor-icons/react";
import {
  Button,
  Card,
  CardContent,
  cn,
  Text,
  ToggleGroup,
  ToggleGroupItem,
} from "@posthog/quill";
import type { OnboardingLandingDestination } from "@posthog/shared/analytics-events";
import { SpacesIcon } from "@posthog/ui/features/canvas/components/SpacesIcon";
import { type ReactNode, useState } from "react";
import { OnboardingCompactFlowLayout } from "./OnboardingCompactFlowLayout";
import { OnboardingConceptPreview } from "./OnboardingConceptPreview";
import { OnboardingCycleFlowLayout } from "./OnboardingCycleFlowLayout";
import { OnboardingFlowLayout } from "./OnboardingFlowLayout";
import { OnboardingGuidedLayout } from "./OnboardingGuidedLayout";
import { OnboardingRailFlowLayout } from "./OnboardingRailFlowLayout";

type OnboardingHref = "/spaces" | "/inbox" | "/canvases" | "/agents" | "/new";
type OnboardingDesign =
  | "current"
  | "guided"
  | "flow"
  | "compact"
  | "rail"
  | "cycle";

interface OnboardingConcept {
  destination: OnboardingLandingDestination;
  title: string;
  description: string;
  buttonLabel: string;
  href: OnboardingHref;
  icon: ReactNode;
}

interface SpaceDetailItemProps {
  icon: ReactNode;
  title: string;
  children: ReactNode;
  className?: string;
}

function SpaceDetailItem({
  icon,
  title,
  children,
  className,
}: SpaceDetailItemProps) {
  return (
    <div className={cn("flex gap-3 py-4", className)}>
      <span className="mt-0.5 flex shrink-0 text-muted-foreground" aria-hidden>
        {icon}
      </span>
      <div className="flex flex-col gap-1">
        <h3 className="font-semibold text-sm">{title}</h3>
        <Text size="sm" variant="muted">
          {children}
        </Text>
      </div>
    </div>
  );
}

const spacesConcept: OnboardingConcept = {
  destination: "spaces",
  title: "Spaces",
  description:
    "Spaces keep related work, context, and people together. Use them for your own work or to work with others.",
  buttonLabel: "Open spaces",
  href: "/spaces",
  icon: <SpacesIcon size={18} />,
};

const cardConcepts: OnboardingConcept[] = [
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
  const [design, setDesign] = useState<OnboardingDesign>("guided");
  const visibleCardConcepts = selfDrivingAvailable
    ? cardConcepts
    : cardConcepts.filter((concept) => concept.destination !== "self-driving");

  return (
    <div className="h-full overflow-auto bg-gray-1">
      <main className="@container mx-auto w-full max-w-5xl px-6 py-8">
        <div className="mb-5 flex justify-end">
          <div className="flex items-center gap-2">
            <Text size="sm" variant="muted">
              Design
            </Text>
            <ToggleGroup
              aria-label="Onboarding design"
              value={[design]}
              onValueChange={(next: string[]) => {
                const selected = next[0];
                if (
                  selected === "current" ||
                  selected === "guided" ||
                  selected === "flow" ||
                  selected === "compact" ||
                  selected === "rail" ||
                  selected === "cycle"
                ) {
                  setDesign(selected);
                }
              }}
            >
              <ToggleGroupItem
                value="current"
                size="sm"
                variant="outline"
                data-attr="onboarding-design-current"
              >
                Current
              </ToggleGroupItem>
              <ToggleGroupItem
                value="guided"
                size="sm"
                variant="outline"
                data-attr="onboarding-design-guided"
              >
                Guided
              </ToggleGroupItem>
              <ToggleGroupItem
                value="flow"
                size="sm"
                variant="outline"
                data-attr="onboarding-design-flow"
              >
                Flow
              </ToggleGroupItem>
              <ToggleGroupItem
                value="compact"
                size="sm"
                variant="outline"
                data-attr="onboarding-design-compact"
              >
                Compact
              </ToggleGroupItem>
              <ToggleGroupItem
                value="rail"
                size="sm"
                variant="outline"
                data-attr="onboarding-design-rail"
              >
                Rail
              </ToggleGroupItem>
              <ToggleGroupItem
                value="cycle"
                size="sm"
                variant="outline"
                data-attr="onboarding-design-cycle"
              >
                Cycle
              </ToggleGroupItem>
            </ToggleGroup>
          </div>
        </div>

        <div data-attr="onboarding-design" data-design={design}>
          {design === "cycle" ? (
            <OnboardingCycleFlowLayout
              selfDrivingAvailable={selfDrivingAvailable}
              onOpenDestination={onOpenDestination}
            />
          ) : design === "rail" ? (
            <OnboardingRailFlowLayout
              selfDrivingAvailable={selfDrivingAvailable}
              onOpenDestination={onOpenDestination}
            />
          ) : design === "compact" ? (
            <OnboardingCompactFlowLayout
              selfDrivingAvailable={selfDrivingAvailable}
              onOpenDestination={onOpenDestination}
            />
          ) : design === "flow" ? (
            <OnboardingFlowLayout
              selfDrivingAvailable={selfDrivingAvailable}
              onOpenDestination={onOpenDestination}
            />
          ) : design === "guided" ? (
            <OnboardingGuidedLayout
              selfDrivingAvailable={selfDrivingAvailable}
              onOpenDestination={onOpenDestination}
            />
          ) : (
            <>
              <div className="mb-6 flex max-w-2xl flex-col gap-2">
                <h1 className="font-bold text-xl">
                  Get to know PostHog Desktop
                </h1>
                <Text variant="muted">
                  Choose a concept to learn more. Each link opens in a new tab.
                </Text>
              </div>

              <section className="mb-6">
                <div className="grid @3xl:grid-cols-2 grid-cols-1 @3xl:items-center gap-6">
                  <OnboardingConceptPreview destination="spaces" />
                  <div className="flex flex-col items-start gap-3">
                    <div className="flex items-center gap-2 text-foreground">
                      <span className="flex shrink-0 items-center" aria-hidden>
                        {spacesConcept.icon}
                      </span>
                      <h2 className="font-bold text-lg">
                        {spacesConcept.title}
                      </h2>
                    </div>
                    <Text variant="muted">{spacesConcept.description}</Text>
                    <Button
                      nativeButton={false}
                      variant="outline"
                      data-attr="onboarding-open-spaces"
                      render={
                        // biome-ignore lint/a11y/useAnchorContent: Base UI adds the button text to this anchor.
                        <a
                          href={spacesConcept.href}
                          aria-label={spacesConcept.buttonLabel}
                          onClick={(event) => {
                            event.preventDefault();
                            onOpenDestination(
                              spacesConcept.destination,
                              spacesConcept.href,
                            );
                          }}
                        />
                      }
                    >
                      {spacesConcept.buttonLabel}
                    </Button>
                  </div>
                </div>

                <div className="mt-5 grid @3xl:grid-cols-2 grid-cols-1 border-border border-y">
                  <SpaceDetailItem
                    icon={<LockSimpleIcon size={18} />}
                    title="Personal space"
                    className="border-border border-b @3xl:pr-6"
                  >
                    Your private space for sessions, canvases, and context. Only
                    you can access it.
                  </SpaceDetailItem>
                  <SpaceDetailItem
                    icon={<UsersThreeIcon size={18} />}
                    title="Public space"
                    className="border-border border-b @3xl:border-l @3xl:pl-6"
                  >
                    A shared space for a team or area of work. People in the
                    space can work together.
                  </SpaceDetailItem>
                  <SpaceDetailItem
                    icon={<ChatsCircleIcon size={18} />}
                    title="Feed"
                    className="border-border border-b @3xl:border-b-0 @3xl:pr-6"
                  >
                    The Feed shows every session started in the space, newest
                    first. Everyone can follow its progress and reply in its
                    thread.
                  </SpaceDetailItem>
                  <SpaceDetailItem
                    icon={<BookOpenTextIcon size={18} />}
                    title="Context"
                    className="@3xl:border-border @3xl:border-l @3xl:pl-6"
                  >
                    Context stores the space&apos;s shared CONTEXT.md with
                    conventions, key files, and other background. Agents read it
                    when relevant to their task.
                  </SpaceDetailItem>
                </div>
              </section>

              <div className="grid @3xl:grid-cols-2 grid-cols-1 gap-4">
                {visibleCardConcepts.map((concept) => (
                  <Card
                    key={concept.destination}
                    className="grid h-full grid-cols-2 gap-0 overflow-hidden py-0"
                  >
                    <OnboardingConceptPreview
                      destination={concept.destination}
                    />
                    <CardContent className="flex min-w-0 flex-col gap-3 p-4">
                      <div className="flex items-center gap-2 text-foreground">
                        <span
                          className="flex shrink-0 items-center"
                          aria-hidden
                        >
                          {concept.icon}
                        </span>
                        <h2 className="font-bold text-base">{concept.title}</h2>
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
                              onOpenDestination(
                                concept.destination,
                                concept.href,
                              );
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
            </>
          )}
        </div>
      </main>
    </div>
  );
}
