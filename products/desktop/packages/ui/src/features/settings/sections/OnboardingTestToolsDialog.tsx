import {
  Button,
  Checkbox,
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  RadioGroup,
  RadioGroupItem,
} from "@posthog/quill";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { closeSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { toast } from "@posthog/ui/primitives/toast";
import { navigateToChannelTask } from "@posthog/ui/router/navigationBridge";
import { type ReactElement, type ReactNode, useState } from "react";

function commaSeparated(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function prose(items: string[]): string {
  if (items.length <= 1) {
    return items[0] ?? "";
  }
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/**
 * One answer per branch of `onboarding_brief._status_line`. That cascade picks a
 * single status line, so these are alternatives rather than independent facts.
 */
type Situation =
  | "nothing-connected"
  | "findings-waiting"
  | "just-switched-on"
  | "already-watching";

interface Draft {
  joining: boolean;
  companyDomain: string;
  otherMembers: string;
  situation: Situation;
  findingsWaiting: number;
  sourcesWatching: string;
  sourcesEnabled: string;
  includeTeachingCanvas: boolean;
}

const DEFAULT_DRAFT: Draft = {
  joining: false,
  companyDomain: "posthog.com",
  otherMembers: "Max, Lotte",
  situation: "nothing-connected",
  findingsWaiting: 3,
  sourcesWatching: "errors, conversion drops",
  sourcesEnabled: "error tracking, web analytics",
  includeTeachingCanvas: true,
};

/** Mirrors `onboarding_brief.build_opening_brief`. */
function describeOpeningMessage(draft: Draft): string[] {
  const lines: string[] = [];
  const members = prose(commaSeparated(draft.otherMembers));
  const domain = draft.companyDomain.trim();

  if (draft.joining) {
    lines.push(
      members
        ? `Welcome them and say ${members} are already here`
        : "Welcome them to the workspace",
    );
  } else if (domain) {
    lines.push(`Read ${domain} and summarize what the company does`);
  } else {
    lines.push("Welcome them, with no company research");
  }

  if (draft.situation === "nothing-connected") {
    lines.push("Say no data is arriving yet, because nothing is connected");
    lines.push("Offer to add PostHog and open a pull request");
  } else if (draft.situation === "findings-waiting") {
    lines.push(
      `Say ${draft.findingsWaiting} findings are waiting in Self-driving`,
    );
    lines.push("Offer to walk them through one of the findings");
  } else if (draft.situation === "just-switched-on") {
    const watching = prose(commaSeparated(draft.sourcesWatching));
    if (watching) {
      lines.push(`Say PostHog is now watching for ${watching}`);
    }
  } else {
    const enabled = prose(commaSeparated(draft.sourcesEnabled));
    if (enabled) {
      lines.push(`Say PostHog is already watching ${enabled}`);
    }
  }

  if (draft.includeTeachingCanvas) {
    lines.push("Mention the teaching canvas and offer to open it");
  }
  return lines;
}

function toRequest(draft: Draft) {
  return {
    company_domain: draft.joining ? "" : draft.companyDomain.trim(),
    joining_existing_organization: draft.joining,
    has_events: draft.situation !== "nothing-connected",
    signal_reports_waiting:
      draft.situation === "findings-waiting" ? draft.findingsWaiting : 0,
    other_members: draft.joining ? commaSeparated(draft.otherMembers) : [],
    sources_enabled:
      draft.situation === "already-watching"
        ? commaSeparated(draft.sourcesEnabled)
        : [],
    sources_watching:
      draft.situation === "just-switched-on"
        ? commaSeparated(draft.sourcesWatching)
        : [],
    sources_newly_enabled: draft.situation === "just-switched-on",
    include_teaching_canvas: draft.includeTeachingCanvas,
  };
}

function Question({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}): ReactElement {
  return (
    <div className="flex flex-col gap-2">
      <span className="font-medium text-[13px] text-gray-12">{label}</span>
      {children}
    </div>
  );
}

function Choice({
  id,
  value,
  label,
  children,
}: {
  id: string;
  value: string;
  label: string;
  children?: ReactNode;
}): ReactElement {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-2">
        <RadioGroupItem value={value} id={id} />
        <Label htmlFor={id} className="font-normal">
          {label}
        </Label>
      </div>
      {children && <div className="pl-6">{children}</div>}
    </div>
  );
}

export function OnboardingTestToolsDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}): ReactElement {
  const client = useAuthenticatedClient();
  const [draft, setDraft] = useState<Draft>(DEFAULT_DRAFT);
  const [starting, setStarting] = useState(false);

  const patch = (values: Partial<Draft>): void =>
    setDraft((current) => ({ ...current, ...values }));

  const startSession = async (): Promise<void> => {
    setStarting(true);
    try {
      const result = await client.startOnboardingTestSession(toRequest(draft));
      onOpenChange(false);
      closeSettings();
      navigateToChannelTask(result.channel_id, result.task_id);
    } catch (error) {
      toast.error("Couldn't start the onboarding test session", {
        description: error instanceof Error ? error.message : undefined,
      });
    } finally {
      setStarting(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && starting) {
          return;
        }
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-lg" showCloseButton={!starting}>
        <DialogHeader>
          <DialogTitle>Test the first-run session</DialogTitle>
          <DialogDescription>
            See what the agent opens with in a given situation.
          </DialogDescription>
        </DialogHeader>

        <DialogBody>
          <div className="flex flex-col gap-6">
            <Question label="Who's arriving">
              <RadioGroup
                value={draft.joining ? "joining" : "first"}
                onValueChange={(value) =>
                  patch({ joining: value === "joining" })
                }
                className="gap-3"
              >
                <Choice
                  id="arriving-first"
                  value="first"
                  label="The first person in the workspace"
                >
                  {!draft.joining && (
                    <Input
                      aria-label="Company domain"
                      value={draft.companyDomain}
                      onChange={(event) =>
                        patch({ companyDomain: event.target.value })
                      }
                      placeholder="Company domain, or empty to skip research"
                    />
                  )}
                </Choice>
                <Choice
                  id="arriving-joining"
                  value="joining"
                  label="Joining people who are already here"
                >
                  {draft.joining && (
                    <Input
                      aria-label="Who's already here"
                      value={draft.otherMembers}
                      onChange={(event) =>
                        patch({ otherMembers: event.target.value })
                      }
                      placeholder="Who's already here, comma separated"
                    />
                  )}
                </Choice>
              </RadioGroup>
            </Question>

            <Question label="What's happening in the project">
              <RadioGroup
                value={draft.situation}
                onValueChange={(value) =>
                  patch({ situation: value as Situation })
                }
                className="gap-3"
              >
                <Choice
                  id="situation-nothing"
                  value="nothing-connected"
                  label="Nothing is connected yet"
                />
                <Choice
                  id="situation-findings"
                  value="findings-waiting"
                  label="Findings are waiting"
                >
                  {draft.situation === "findings-waiting" && (
                    <Input
                      aria-label="How many findings"
                      type="number"
                      min={1}
                      className="w-24"
                      value={draft.findingsWaiting}
                      onChange={(event) =>
                        patch({
                          findingsWaiting: Math.max(
                            1,
                            Number(event.target.value),
                          ),
                        })
                      }
                    />
                  )}
                </Choice>
                <Choice
                  id="situation-switched-on"
                  value="just-switched-on"
                  label="Sources were just switched on"
                >
                  {draft.situation === "just-switched-on" && (
                    <Input
                      aria-label="What PostHog now watches for"
                      value={draft.sourcesWatching}
                      onChange={(event) =>
                        patch({ sourcesWatching: event.target.value })
                      }
                      placeholder="errors, conversion drops"
                    />
                  )}
                </Choice>
                <Choice
                  id="situation-watching"
                  value="already-watching"
                  label="PostHog is already watching"
                >
                  {draft.situation === "already-watching" && (
                    <Input
                      aria-label="What PostHog already watches"
                      value={draft.sourcesEnabled}
                      onChange={(event) =>
                        patch({ sourcesEnabled: event.target.value })
                      }
                      placeholder="error tracking, web analytics"
                    />
                  )}
                </Choice>
              </RadioGroup>
            </Question>

            <div className="flex flex-col gap-2 rounded-(--radius-3) border border-(--gray-5) bg-gray-2 p-3">
              <span className="font-medium text-[13px] text-gray-12">
                The agent will
              </span>
              <ol className="m-0 flex list-none flex-col gap-1.5 p-0">
                {describeOpeningMessage(draft).map((line, index) => (
                  <li
                    key={line}
                    className="flex gap-2 text-[12px] text-gray-11 leading-snug"
                  >
                    <span className="text-gray-9 tabular-nums">
                      {index + 1}.
                    </span>
                    <span>{line}</span>
                  </li>
                ))}
              </ol>
              <div className="mt-1 flex items-center gap-2">
                <Checkbox
                  id="include-teaching-canvas"
                  checked={draft.includeTeachingCanvas}
                  onCheckedChange={(checked) =>
                    patch({ includeTeachingCanvas: checked === true })
                  }
                />
                <Label
                  htmlFor="include-teaching-canvas"
                  className="font-normal text-[12px] text-gray-11"
                >
                  Include the teaching canvas
                </Label>
              </div>
            </div>
          </div>
        </DialogBody>

        <DialogFooter>
          <DialogClose
            render={
              <Button variant="outline" size="sm" disabled={starting}>
                Cancel
              </Button>
            }
          />
          <Button
            variant="primary"
            size="sm"
            loading={starting}
            onClick={() => void startSession()}
          >
            Start session
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
