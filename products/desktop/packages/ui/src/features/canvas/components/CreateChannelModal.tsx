import { validateChannelName } from "@posthog/core/canvas/channelName";
import {
  Button,
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
  Input,
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemTitle,
  Label,
  Switch,
  Textarea,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { RepositoriesField } from "@posthog/ui/features/canvas/components/RepositoriesField";
import { useChannelMutations } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useGenerateContext } from "@posthog/ui/features/canvas/hooks/useGenerateContext";
import { useUpdateTaskChannelRepositories } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { AnimatedHeight } from "@posthog/ui/primitives/AnimatedHeight";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useNavigate } from "@tanstack/react-router";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useEffect, useId, useRef, useState } from "react";

// Matches Slack's "Create a channel" naming constraint.
const MAX_CONTEXT_NAME_LENGTH = 80;

const DESCRIPTION_EXAMPLES = [
  "Feature flags help teams control feature access, target specific users, and manage gradual rollouts.",
  "The onboarding experience guides new customers from creating an account to completing their first successful setup.",
  "We're migrating our billing system to Stripe while preserving existing subscriptions and minimizing disruption.",
  "Authentication includes sign-in, account recovery, session management, roles, and permissions across our applications.",
  "The mobile redesign aims to simplify navigation, improve accessibility, and make common workflows faster.",
];

const DESCRIPTION_ROTATION_INTERVAL_MS = 5000;

const CREATE_STEPS = ["name", "describe", "repositories"] as const;
type CreateStep = (typeof CREATE_STEPS)[number];

// quill's dialog curves, so a step swap reads as part of the same surface. A
// step enters and leaves (ease-out); the card's height morphs in place behind
// it (ease-in-out), starting once the arriving step has been measured.
const EASE_OUT: [number, number, number, number] = [0.215, 0.61, 0.355, 1];
const EASE_IN_OUT: [number, number, number, number] = [0.645, 0.045, 0.355, 1];
const STEP_DURATION = 0.2;
// Enough travel to say which way the flow went without the text sliding far
// enough to read as a page turn.
const STEP_SHIFT = 12;

function RotatingDescriptionPlaceholder({ visible }: { visible: boolean }) {
  const [exampleIndex, setExampleIndex] = useState(0);
  const reduceMotion = useReducedMotion();

  useEffect(() => {
    if (!visible || reduceMotion) return;

    const interval = window.setInterval(() => {
      setExampleIndex((current) => (current + 1) % DESCRIPTION_EXAMPLES.length);
    }, DESCRIPTION_ROTATION_INTERVAL_MS);

    return () => window.clearInterval(interval);
  }, [reduceMotion, visible]);

  return (
    <AnimatePresence initial={false} mode="wait">
      {visible && (
        <motion.div
          key={exampleIndex}
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 border border-transparent px-2 py-2 text-muted-foreground text-xs leading-4"
          initial={reduceMotion ? false : { opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={reduceMotion ? undefined : { opacity: 0, y: -4 }}
          transition={{ duration: reduceMotion ? 0 : 0.2 }}
        >
          {DESCRIPTION_EXAMPLES[exampleIndex]}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

interface CreateChannelModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  // When set, the dialog is the "Create your CONTEXT.md" flow for an existing
  // context: no name field, just a description that seeds the planning session.
  existingContext?: { channelId: string; channelName: string };
}

// Two dialogs in one, split on `existingContext`:
// - Create mode: three steps in one dialog, swapping its content as you go.
//   Step one names the channel, step two asks what it's about, step three
//   carries the settings. Nothing is created until that last step resolves —
//   "Create" makes the channel, links the chosen repositories and launches the
//   context.md plan session seeded by the description, "Skip" makes the channel
//   alone. Either way the user lands in the channel's feed, whose intro card
//   carries the onboarding (and offers context.md later if skipped).
// - Describe mode: the "Create your context.md" dialog (opened from the intro
//   card or the CONTEXT.md empty state). A single textarea whose text seeds
//   a plan-mode session that builds the context's CONTEXT.md with the user.
export function CreateChannelModal({
  open,
  onOpenChange,
  existingContext,
}: CreateChannelModalProps) {
  const isDescribeMode = !!existingContext;
  const spacesLayout = useChannelsLayout();
  const { createChannel, isCreating } = useChannelMutations();
  const { generate, isStarting } = useGenerateContext();
  const linkRepositories = useUpdateTaskChannelRepositories();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [repositories, setRepositories] = useState<string[]>([]);
  const [repositoryIntegration, setRepositoryIntegration] = useState<
    number | null
  >(null);
  const [star, setStar] = useState(true);
  // Create mode's step. Describe mode returns before this is read.
  const [step, setStep] = useState<CreateStep>("name");
  // Which way the last move went, so a step slides in from the side it came
  // from. Derived from the step order, so no call site can disagree.
  const [direction, setDirection] = useState(1);
  const descriptionHelperId = useId();
  const reduceMotion = useReducedMotion();
  const stepDuration = reduceMotion ? 0 : STEP_DURATION;

  const goToStep = (next: CreateStep) => {
    setDirection(
      CREATE_STEPS.indexOf(next) > CREATE_STEPS.indexOf(step) ? 1 : -1,
    );
    setStep(next);
  };

  // Reset the fields each time the modal opens so a previous draft never
  // lingers. Adjusted inline during render (prev-prop comparison) rather than in
  // an effect, which would flash a stale value for one commit.
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setName("");
      setDescription("");
      setRepositories([]);
      setRepositoryIntegration(null);
      setStar(true);
      setStep("name");
    }
  }

  const trimmedName = name.trim();
  const trimmedDescription = description.trim();
  const remaining = MAX_CONTEXT_NAME_LENGTH - name.length;
  const nameError = isDescribeMode ? null : validateChannelName(trimmedName);

  const busy = isCreating || isStarting || linkRepositories.isPending;
  const canAdvance = !busy && !!trimmedName && !nameError;
  const canDescribe = !busy && !!trimmedDescription;

  // `busy` only disables the buttons a render after the mutation starts, so a
  // double-click lands two submits before it applies. Create is resolve-or-
  // create (idempotent), but a double submit would still double-launch the
  // plan session. Latch synchronously; the buttons stay the user-visible half.
  const submittingRef = useRef(false);
  const submitOnce = async (submit: () => Promise<void>) => {
    if (submittingRef.current) return;
    submittingRef.current = true;
    try {
      await submit();
    } finally {
      submittingRef.current = false;
    }
  };

  const submitCreate = async (linkSelectedRepositories: boolean) => {
    let contextId: string;
    try {
      const channel = await createChannel(trimmedName, { star });
      track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
        action_type: "create",
        surface: "sidebar",
        channel_id: channel.id,
        success: true,
      });
      contextId = channel.id;
    } catch (error) {
      track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
        action_type: "create",
        surface: "sidebar",
        success: false,
      });
      toast.error(`Couldn't create ${spacesLayout ? "space" : "channel"}`, {
        description: error instanceof Error ? error.message : String(error),
      });
      return;
    }

    if (linkSelectedRepositories && repositories.length > 0) {
      try {
        await linkRepositories.mutateAsync({
          channelId: contextId,
          githubIntegration: repositoryIntegration,
          repositories,
        });
      } catch (error) {
        toast.error("Couldn't link repositories", {
          description: error instanceof Error ? error.message : String(error),
        });
      }
    }

    if (trimmedDescription) {
      track(ANALYTICS_EVENTS.CONTEXT_ACTION, {
        action_type: "generate_started",
        channel_id: contextId,
      });
      // Failure is fine to swallow here (generate() already toasted): the
      // context exists, so land the user on it — the intro card offers the
      // retry.
      await generate({
        channelId: contextId,
        channelName: trimmedName,
        description: trimmedDescription,
      });
    }

    onOpenChange(false);
    void navigate({
      to: "/website/$channelId",
      params: { channelId: contextId },
    });
  };

  // Describe mode: launch the plan-mode session that builds CONTEXT.md. On
  // failure (generate() already toasted) the dialog stays open, state intact,
  // for a clean retry.
  const submitDescribe = async () => {
    if (!existingContext) return;
    track(ANALYTICS_EVENTS.CONTEXT_ACTION, {
      action_type: "generate_started",
      channel_id: existingContext.channelId,
    });
    const task = await generate({
      channelId: existingContext.channelId,
      channelName: existingContext.channelName,
      description: trimmedDescription,
    });
    if (!task) return;

    // Land on the context index (its feed), where the announcement and the plan
    // task card show. The user clicks the card to open the session.
    onOpenChange(false);
    void navigate({
      to: "/website/$channelId",
      params: { channelId: existingContext.channelId },
    });
  };

  const submitDescribeStep = async () => {
    if (isDescribeMode) {
      if (!canDescribe) return;
      await submitDescribe();
      return;
    }
    if (canDescribe) goToStep("repositories");
  };

  // Both surfaces ask the same thing — the create step in its header, describe
  // mode on the field itself — so the copy is written once.
  const aboutTitle = `What's this ${spacesLayout ? "space" : "channel"} about?`;
  const aboutBlurb = `Tell PostHog about this ${
    spacesLayout ? "space" : "channel"
  }. We'll use it to create a CONTEXT.md file with relevant information for future tasks.`;

  const descriptionField = (
    <Field>
      {/* In create mode the step's own header asks the question, so the label
          would just repeat it. */}
      {isDescribeMode && (
        <>
          <FieldLabel htmlFor="context-description">{aboutTitle}</FieldLabel>
          <FieldDescription id={descriptionHelperId}>
            {aboutBlurb}
          </FieldDescription>
        </>
      )}
      <div className="relative">
        <Textarea
          id="context-description"
          aria-describedby={descriptionHelperId}
          rows={4}
          className="max-h-[40vh] overflow-y-auto text-xs leading-4"
          value={description}
          disabled={busy}
          onChange={(e) => setDescription(e.target.value)}
          onKeyDown={(e) => {
            // ⌘/Ctrl+Enter submits; a bare Enter stays a newline. Held down it
            // repeats, so it goes through the same latch as the buttons.
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              void submitOnce(submitDescribeStep);
            }
          }}
        />
        <RotatingDescriptionPlaceholder
          visible={description.length === 0 && !busy}
        />
      </div>
    </Field>
  );

  // Describe mode has no steps to walk — the channel already exists, so the
  // dialog is only ever this one question.
  if (isDescribeMode) {
    return (
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (!busy) onOpenChange(next);
        }}
      >
        <DialogContent showCloseButton={false} className="sm:max-w-lg">
          {/* No visible header here — the textarea's label carries the dialog;
              the title stays for screen readers. */}
          <DialogTitle className="sr-only">Create your context.md</DialogTitle>
          <DialogBody viewportClassName="flex flex-col gap-4">
            {descriptionField}
          </DialogBody>
          <DialogFooter>
            <DialogClose
              render={
                <Button variant="outline" disabled={busy}>
                  Cancel
                </Button>
              }
            />
            <Button
              variant="primary"
              disabled={!canDescribe}
              loading={busy}
              onClick={() => void submitOnce(submitDescribeStep)}
            >
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  }

  // Only the live step is built — the others cost nothing until you reach them.
  const renderStep = () => {
    switch (step) {
      case "name":
        return (
          <>
            <DialogHeader>
              <DialogTitle>
                Create a {spacesLayout ? "space" : "channel"}
              </DialogTitle>
            </DialogHeader>

            <DialogBody className="flex max-h-[55vh] flex-col gap-4">
              <Field>
                <FieldLabel htmlFor="context-name">Name</FieldLabel>
                <Input
                  id="context-name"
                  autoFocus
                  value={name}
                  placeholder="e.g. mobile"
                  maxLength={MAX_CONTEXT_NAME_LENGTH}
                  disabled={busy}
                  onChange={(e) => setName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      if (canAdvance) goToStep("describe");
                    }
                  }}
                />
                {nameError ? (
                  <FieldError>{nameError}</FieldError>
                ) : (
                  <span className="text-gray-9 text-xs tabular-nums">
                    {remaining} left
                  </span>
                )}
              </Field>
            </DialogBody>

            <DialogFooter>
              <DialogClose
                render={
                  <Button variant="outline" disabled={busy}>
                    Cancel
                  </Button>
                }
              />
              <Button
                variant="primary"
                disabled={!canAdvance}
                onClick={() => goToStep("describe")}
              >
                Next
              </Button>
            </DialogFooter>
          </>
        );
      case "describe":
        return (
          <>
            <DialogHeader>
              <DialogTitle>{aboutTitle}</DialogTitle>
              <DialogDescription id={descriptionHelperId}>
                {aboutBlurb}
              </DialogDescription>
            </DialogHeader>

            <DialogBody viewportClassName="flex flex-col gap-4">
              {descriptionField}
            </DialogBody>

            <DialogFooter>
              <Button
                variant="outline"
                className="sm:mr-auto"
                disabled={busy}
                onClick={() => goToStep("name")}
              >
                Back
              </Button>
              <Button
                variant="default"
                disabled={busy}
                onClick={() => {
                  setDescription("");
                  goToStep("repositories");
                }}
              >
                Skip
              </Button>
              <Button
                variant="primary"
                disabled={!canDescribe}
                onClick={() => void submitOnce(submitDescribeStep)}
              >
                Next
              </Button>
            </DialogFooter>
          </>
        );
      case "repositories":
        return (
          <>
            <DialogHeader>
              <DialogTitle>Settings</DialogTitle>
            </DialogHeader>

            <DialogBody viewportClassName="flex flex-col gap-3">
              <Item variant="outline">
                <ItemContent>
                  <ItemTitle>Repositories</ItemTitle>
                  <ItemDescription>
                    New tasks in this {spacesLayout ? "space" : "channel"} can
                    use these repositories. You can change them later.
                  </ItemDescription>
                </ItemContent>
                <ItemActions>
                  <RepositoriesField
                    selected={repositories}
                    integrationId={repositoryIntegration}
                    disabled={busy}
                    onChange={(nextRepositories, nextIntegration) => {
                      setRepositories(nextRepositories);
                      setRepositoryIntegration(nextIntegration);
                    }}
                  />
                </ItemActions>
              </Item>
              {/* Last stop before both create buttons, so the toggle is in view when
              the space is actually made. */}
              <Item variant="outline">
                <ItemContent>
                  <ItemTitle>
                    <Label htmlFor="context-star">
                      Star new {spacesLayout ? "space" : "channel"}
                    </Label>
                  </ItemTitle>
                  <ItemDescription>
                    Shows it in your starred list.
                  </ItemDescription>
                </ItemContent>
                <ItemActions>
                  <Switch
                    id="context-star"
                    checked={star}
                    disabled={busy}
                    onCheckedChange={setStar}
                  />
                </ItemActions>
              </Item>
            </DialogBody>

            <DialogFooter>
              <Button
                variant="outline"
                className="sm:mr-auto"
                disabled={busy}
                onClick={() => goToStep("describe")}
              >
                Back
              </Button>
              <Button
                variant="default"
                disabled={busy}
                onClick={() => void submitOnce(() => submitCreate(false))}
              >
                Skip
              </Button>
              <Button
                variant="primary"
                disabled={busy || repositories.length === 0}
                loading={busy}
                onClick={() => void submitOnce(() => submitCreate(true))}
              >
                Create
              </Button>
            </DialogFooter>
          </>
        );
    }
  };

  // The exiting step is popped out of flow, so the card's height follows the
  // arriving one. `relative` is what that pop positions against.
  const stepDirection = reduceMotion ? 0 : direction;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (busy || next) return;
        // Escape and the backdrop walk the steps back, the way the buttons do.
        // Closing outright from the last step would drop a filled-in draft,
        // since reopening starts clean.
        const previous = CREATE_STEPS[CREATE_STEPS.indexOf(step) - 1];
        if (previous) {
          goToStep(previous);
          return;
        }
        onOpenChange(false);
      }}
    >
      <DialogContent showCloseButton={false} className="sm:max-w-lg">
        <AnimatedHeight
          className="relative"
          duration={stepDuration}
          ease={EASE_IN_OUT}
        >
          <AnimatePresence
            initial={false}
            mode="popLayout"
            custom={stepDirection}
          >
            <motion.div
              key={step}
              className="flex max-h-[70vh] flex-col"
              custom={stepDirection}
              transition={{ duration: stepDuration, ease: EASE_OUT }}
              variants={{
                enter: (d: number) => ({ opacity: 0, x: d * STEP_SHIFT }),
                center: { opacity: 1, x: 0 },
                exit: (d: number) => ({
                  opacity: 0,
                  x: -d * STEP_SHIFT,
                  // Shorter than the entrance, so the arriving step leads.
                  transition: {
                    duration: stepDuration * 0.75,
                    ease: EASE_OUT,
                  },
                }),
              }}
              initial="enter"
              animate="center"
              exit="exit"
            >
              {renderStep()}
            </motion.div>
          </AnimatePresence>
        </AnimatedHeight>
      </DialogContent>
    </Dialog>
  );
}
