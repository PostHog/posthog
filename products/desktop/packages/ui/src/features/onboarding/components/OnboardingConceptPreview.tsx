import {
  CaretDownIcon,
  CaretRightIcon,
  CheckCircleIcon,
  FileTextIcon,
  ListChecksIcon,
  LockSimpleIcon,
  MagnifyingGlassIcon,
  RobotIcon,
  SquaresFourIcon,
  TrayIcon,
} from "@phosphor-icons/react";
import { Avatar, AvatarFallback, AvatarGroup, Spinner } from "@posthog/quill";
import type { OnboardingLandingDestination } from "@posthog/shared/analytics-events";
import type { ReactNode } from "react";

export interface OnboardingConceptPreviewProps {
  destination: OnboardingLandingDestination;
  placement?: "side" | "top";
}

const AVATAR_TONES = [
  "bg-blue-3 text-blue-11",
  "bg-violet-3 text-violet-11",
  "bg-green-3 text-green-11",
] as const;

function renderAvatars(initials: readonly string[]): ReactNode {
  return (
    <AvatarGroup stacked reverse size="xs">
      {initials.map((initial, index) => (
        <Avatar key={initial} size="xs">
          <AvatarFallback
            className={`font-semibold text-[8px] ${AVATAR_TONES[index % AVATAR_TONES.length]}`}
          >
            {initial}
          </AvatarFallback>
        </Avatar>
      ))}
    </AvatarGroup>
  );
}

function renderPreview(destination: OnboardingLandingDestination): ReactNode {
  switch (destination) {
    case "spaces":
      return (
        <div className="flex h-full flex-col">
          <div className="border-border border-b px-3 py-2 font-semibold text-[11px] text-foreground">
            Spaces
          </div>
          <div className="px-3 py-2">
            <div className="flex items-center gap-2 rounded-(--radius-2) border border-border bg-gray-2 px-2 py-1.5 text-[9px] text-muted-foreground">
              <MagnifyingGlassIcon size={11} />
              <span>Search spaces...</span>
            </div>
          </div>
          <div className="flex min-h-0 flex-1 flex-col gap-0.5 px-3 pb-2">
            <div className="flex items-center gap-1 py-0.5 font-semibold text-[8px] text-muted-foreground uppercase tracking-wide">
              <span>Starred</span>
              <CaretDownIcon size={9} />
            </div>
            <div className="flex items-center gap-1.5 rounded-(--radius-2) bg-gray-4 px-2 py-1.5">
              <CaretRightIcon size={10} className="text-muted-foreground" />
              <LockSimpleIcon size={11} className="text-foreground" />
              <span className="flex-1 font-medium text-[10px] text-foreground">
                Personal
              </span>
            </div>
            <div className="flex items-center gap-1.5 px-2 py-1">
              <CaretRightIcon size={10} className="text-muted-foreground" />
              <span className="flex-1 font-medium text-[10px] text-foreground">
                General
              </span>
              {renderAvatars(["AL", "MK", "JP"])}
            </div>
            <div className="mt-1 flex items-center gap-1 py-0.5 font-semibold text-[8px] text-muted-foreground uppercase tracking-wide">
              <span>Spaces</span>
              <CaretDownIcon size={9} />
            </div>
            <div className="flex items-center gap-1.5 px-2 py-1">
              <CaretRightIcon size={10} className="text-muted-foreground" />
              <span className="font-medium text-[10px] text-foreground">
                team-synergy
              </span>
            </div>
          </div>
        </div>
      );
    case "self-driving":
      return (
        <>
          <div className="flex items-center justify-between border-border border-b px-3 py-2">
            <div className="flex items-center gap-1.5 font-medium text-[10px] text-foreground">
              <TrayIcon size={12} />
              <span>Inbox</span>
            </div>
            <span className="rounded-full bg-blue-3 px-1.5 py-0.5 font-medium text-[8px] text-blue-11">
              2 ready
            </span>
          </div>
          <div className="flex flex-1 flex-col justify-center divide-y divide-border px-3">
            {[
              ["Checkout drop-off", "New"],
              ["Payment errors", "Review"],
            ].map(([title, status], index) => (
              <div key={title} className="flex items-center gap-2 py-2.5">
                <span
                  className={`size-2 shrink-0 rounded-full ${index === 0 ? "bg-blue-9" : "bg-orange-9"}`}
                />
                <div className="min-w-0 flex-1">
                  <div className="font-medium text-[10px] text-foreground">
                    {title}
                  </div>
                  <div className="mt-1 h-1.5 w-2/3 rounded-full bg-gray-5" />
                </div>
                <span className="text-[8px] text-muted-foreground">
                  {status}
                </span>
              </div>
            ))}
          </div>
        </>
      );
    case "canvases":
      return (
        <>
          <div className="flex items-center gap-1.5 border-border border-b px-3 py-2 font-medium text-[10px] text-foreground">
            <SquaresFourIcon size={12} />
            <span>Weekly metrics</span>
          </div>
          <div className="grid flex-1 grid-cols-[1.2fr_0.8fr] gap-2 p-3">
            <div className="flex items-end gap-1 rounded-(--radius-2) border border-border bg-card px-2 pt-4 pb-2">
              {["h-1/3", "h-1/2", "h-2/5", "h-2/3", "h-3/5", "h-4/5"].map(
                (height) => (
                  <span
                    key={height}
                    className={`flex-1 rounded-t-sm bg-primary/70 ${height}`}
                  />
                ),
              )}
            </div>
            <div className="flex flex-col gap-2 rounded-(--radius-2) border border-border bg-card p-2">
              <FileTextIcon size={12} className="text-muted-foreground" />
              <div className="h-1.5 w-full rounded-full bg-gray-6" />
              <div className="h-1.5 w-4/5 rounded-full bg-gray-5" />
              <div className="h-1.5 w-3/5 rounded-full bg-gray-5" />
            </div>
          </div>
        </>
      );
    case "agents":
      return (
        <>
          <div className="flex items-center gap-1.5 border-border border-b px-3 py-2 font-medium text-[10px] text-foreground">
            <RobotIcon size={12} />
            <span>Agents</span>
          </div>
          <div className="flex flex-1 flex-col justify-center gap-2 p-3">
            {[
              ["Responder", "Active", "bg-green-9"],
              ["Scout", "Scanning", "bg-blue-9"],
            ].map(([name, status, tone]) => (
              <div
                key={name}
                className="flex items-center gap-2 rounded-(--radius-2) border border-border bg-card px-2.5 py-2"
              >
                <span className="flex size-5 items-center justify-center rounded-(--radius-2) bg-gray-3 text-muted-foreground">
                  <RobotIcon size={11} />
                </span>
                <span className="flex-1 font-medium text-[10px] text-foreground">
                  {name}
                </span>
                <span className={`size-1.5 rounded-full ${tone}`} />
                <span className="text-[8px] text-muted-foreground">
                  {status}
                </span>
              </div>
            ))}
          </div>
        </>
      );
    case "tasks":
      return (
        <>
          <div className="flex items-center justify-between border-border border-b px-3 py-2">
            <div className="flex items-center gap-1.5 font-medium text-[10px] text-foreground">
              <ListChecksIcon size={12} />
              <span>Update onboarding</span>
            </div>
            <div className="flex items-center gap-1 text-[8px] text-muted-foreground">
              <Spinner className="size-2.5 text-primary" />
              <span>Working</span>
            </div>
          </div>
          <div className="flex flex-1 flex-col justify-center gap-2 p-3">
            <div className="flex items-center gap-2 text-[9px] text-foreground">
              <CheckCircleIcon
                size={12}
                weight="fill"
                className="text-green-9"
              />
              <span>Review existing patterns</span>
            </div>
            <div className="flex items-center gap-2 text-[9px] text-foreground">
              <Spinner className="size-3 text-primary" />
              <span>Build the new view</span>
            </div>
            <div className="ml-5 flex gap-1.5">
              <span className="rounded bg-green-3 px-1.5 py-0.5 text-[8px] text-green-11">
                +24
              </span>
              <span className="rounded bg-red-3 px-1.5 py-0.5 text-[8px] text-red-11">
                -3
              </span>
            </div>
          </div>
        </>
      );
  }
}

export function OnboardingConceptPreview({
  destination,
  placement = "side",
}: OnboardingConceptPreviewProps) {
  return (
    <div
      aria-hidden="true"
      className={`pointer-events-none overflow-hidden rounded-[5px] border-border ${destination === "spaces" ? "h-60 border" : placement === "top" ? "h-40 border-b" : "h-full min-h-48 border-r"}`}
    >
      <div className="flex h-full flex-col overflow-hidden">
        {renderPreview(destination)}
      </div>
    </div>
  );
}
