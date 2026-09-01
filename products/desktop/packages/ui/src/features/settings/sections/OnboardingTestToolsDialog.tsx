import {
  Button,
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Questionnaire,
  QuestionnaireChoice,
  QuestionnaireChoiceDescription,
  QuestionnaireChoices,
  QuestionnaireDescription,
  QuestionnaireInput,
  QuestionnaireItem,
  QuestionnaireNext,
  QuestionnairePrevious,
  QuestionnaireProgress,
  QuestionnaireSubmit,
  QuestionnaireTitle,
} from "@posthog/quill";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { leaveSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { toast } from "@posthog/ui/primitives/toast";
import { navigateToChannelTask } from "@posthog/ui/router/navigationBridge";
import {
  type ChangeEvent,
  type ComponentProps,
  type FormEvent,
  type ReactElement,
  useState,
} from "react";

/** What "PostHog is already watching" stands for, so that answer needs no input. */
const ALREADY_WATCHING = ["error tracking", "web analytics"];

/** What "findings are waiting" stands for, so that answer needs no input. */
const FINDINGS_WAITING = 3;

function commaSeparated(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
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
  sourcesWatching: string;
}

const DEFAULT_DRAFT: Draft = {
  joining: false,
  companyDomain: "posthog.com",
  otherMembers: "Max, Lotte",
  situation: "nothing-connected",
  sourcesWatching: "errors, conversion drops",
};

function toRequest(draft: Draft) {
  return {
    company_domain: draft.joining ? "" : draft.companyDomain.trim(),
    joining_existing_organization: draft.joining,
    has_events: draft.situation !== "nothing-connected",
    signal_reports_waiting:
      draft.situation === "findings-waiting" ? FINDINGS_WAITING : 0,
    other_members: draft.joining ? commaSeparated(draft.otherMembers) : [],
    sources_enabled:
      draft.situation === "already-watching" ? ALREADY_WATCHING : [],
    sources_watching:
      draft.situation === "just-switched-on"
        ? commaSeparated(draft.sourcesWatching)
        : [],
    sources_newly_enabled: draft.situation === "just-switched-on",
  };
}

/** A question answered by typing, so it wears a plain field instead of a choice row. */
function TextAnswer({
  label,
  value,
  onValueChange,
  ...props
}: {
  label: string;
  value: string;
  onValueChange: (value: string) => void;
} & Omit<
  ComponentProps<typeof QuestionnaireInput>,
  "value" | "onChange" | "render"
>): ReactElement {
  return (
    <QuestionnaireChoices>
      <QuestionnaireInput
        aria-label={label}
        value={value}
        onChange={(event: ChangeEvent<HTMLInputElement>) =>
          onValueChange(event.target.value)
        }
        render={(inputProps: ComponentProps<"input">) => (
          <Input {...inputProps} />
        )}
        {...props}
      />
    </QuestionnaireChoices>
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
      leaveSettings();
      navigateToChannelTask(result.channel_id, result.task_id);
    } catch (error) {
      toast.error("Couldn't start the onboarding test session", {
        description: error instanceof Error ? error.message : undefined,
      });
    } finally {
      setStarting(false);
    }
  };

  // Nothing is required, because every question opens on a usable default.
  const questions = [
    { name: "arriving" },
    { name: "company", disabled: draft.joining },
    { name: "members", disabled: !draft.joining },
    { name: "situation" },
    { name: "watching", disabled: draft.situation !== "just-switched-on" },
  ];

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
        {/* `contents` leaves the header, body, and footer in the dialog's own grid. */}
        <Questionnaire
          items={questions}
          className="contents"
          onSubmit={(event: FormEvent<HTMLFormElement>) => {
            event.preventDefault();
            void startSession();
          }}
        >
          <DialogHeader>
            <DialogTitle>Test the first-run session</DialogTitle>
          </DialogHeader>

          <DialogBody viewportClassName="flex flex-col gap-4">
            <QuestionnaireProgress />

            <QuestionnaireItem name="arriving">
              <QuestionnaireTitle>Who is arriving?</QuestionnaireTitle>
              <QuestionnaireChoices>
                <QuestionnaireChoice
                  value="first"
                  checked={!draft.joining}
                  onChange={() => patch({ joining: false })}
                >
                  The first person in the workspace
                </QuestionnaireChoice>
                <QuestionnaireChoice
                  value="joining"
                  checked={draft.joining}
                  onChange={() => patch({ joining: true })}
                >
                  Someone joining people who are already here
                </QuestionnaireChoice>
              </QuestionnaireChoices>
            </QuestionnaireItem>

            <QuestionnaireItem name="company" disabled={draft.joining}>
              <QuestionnaireTitle>
                Which website should the agent read?
              </QuestionnaireTitle>
              <QuestionnaireDescription>
                This is usually pulled from the user's email domain. Leave empty
                to simulate a personal email like gmail.com
              </QuestionnaireDescription>
              <TextAnswer
                label="Company website"
                placeholder="posthog.com"
                value={draft.companyDomain}
                onValueChange={(companyDomain) => patch({ companyDomain })}
              />
            </QuestionnaireItem>

            <QuestionnaireItem name="members" disabled={!draft.joining}>
              <QuestionnaireTitle>
                Who is already in the workspace?
              </QuestionnaireTitle>
              <QuestionnaireDescription>
                The agent names them in its welcome. Separate names with commas,
                or leave this empty to name nobody.
              </QuestionnaireDescription>
              <TextAnswer
                label="People already in the workspace"
                placeholder="Max, Lotte"
                value={draft.otherMembers}
                onValueChange={(otherMembers) => patch({ otherMembers })}
              />
            </QuestionnaireItem>

            <QuestionnaireItem name="situation">
              <QuestionnaireTitle>
                What is happening in the project?
              </QuestionnaireTitle>
              <QuestionnaireChoices>
                <QuestionnaireChoice
                  value="nothing-connected"
                  checked={draft.situation === "nothing-connected"}
                  onChange={() => patch({ situation: "nothing-connected" })}
                >
                  Nothing is connected yet
                  <QuestionnaireChoiceDescription>
                    No data is arriving, so the agent offers to add PostHog and
                    open a pull request.
                  </QuestionnaireChoiceDescription>
                </QuestionnaireChoice>
                <QuestionnaireChoice
                  value="findings-waiting"
                  checked={draft.situation === "findings-waiting"}
                  onChange={() => patch({ situation: "findings-waiting" })}
                >
                  Findings are waiting
                  <QuestionnaireChoiceDescription>
                    Self-driving has {FINDINGS_WAITING} findings, so the agent
                    offers to walk through one.
                  </QuestionnaireChoiceDescription>
                </QuestionnaireChoice>
                <QuestionnaireChoice
                  value="just-switched-on"
                  checked={draft.situation === "just-switched-on"}
                  onChange={() => patch({ situation: "just-switched-on" })}
                >
                  Sources were just switched on
                  <QuestionnaireChoiceDescription>
                    The agent says what PostHog now watches for.
                  </QuestionnaireChoiceDescription>
                </QuestionnaireChoice>
                <QuestionnaireChoice
                  value="already-watching"
                  checked={draft.situation === "already-watching"}
                  onChange={() => patch({ situation: "already-watching" })}
                >
                  PostHog is already watching
                  <QuestionnaireChoiceDescription>
                    The agent says {ALREADY_WATCHING.join(" and ")} are already
                    covered.
                  </QuestionnaireChoiceDescription>
                </QuestionnaireChoice>
              </QuestionnaireChoices>
            </QuestionnaireItem>

            <QuestionnaireItem
              name="watching"
              disabled={draft.situation !== "just-switched-on"}
            >
              <QuestionnaireTitle>
                What does PostHog now watch for?
              </QuestionnaireTitle>
              <QuestionnaireDescription>
                The agent lists these back. Separate them with commas.
              </QuestionnaireDescription>
              <TextAnswer
                label="What PostHog now watches for"
                placeholder="errors, conversion drops"
                value={draft.sourcesWatching}
                onValueChange={(sourcesWatching) => patch({ sourcesWatching })}
              />
            </QuestionnaireItem>
          </DialogBody>

          <DialogFooter>
            <DialogClose
              render={
                <Button variant="outline" size="sm" disabled={starting}>
                  Cancel
                </Button>
              }
            />
            <QuestionnairePrevious
              render={
                <Button variant="outline" size="sm" disabled={starting} />
              }
            >
              Back
            </QuestionnairePrevious>
            <QuestionnaireNext render={<Button variant="primary" size="sm" />}>
              Next
            </QuestionnaireNext>
            <QuestionnaireSubmit
              render={<Button variant="primary" size="sm" loading={starting} />}
            >
              Start session
            </QuestionnaireSubmit>
          </DialogFooter>
        </Questionnaire>
      </DialogContent>
    </Dialog>
  );
}
