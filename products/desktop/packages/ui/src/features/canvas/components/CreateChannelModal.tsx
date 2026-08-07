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
  Text,
  Textarea,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { RepositoriesField } from "@posthog/ui/features/canvas/components/RepositoriesField";
import { useChannelMutations } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useGenerateContext } from "@posthog/ui/features/canvas/hooks/useGenerateContext";
import { useUpdateTaskChannelRepositories } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useNavigate } from "@tanstack/react-router";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { type CSSProperties, useEffect, useId, useRef, useState } from "react";

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
// - Create mode: two steps. Step one names the channel; "Next" advances to step
//   two, which asks what it's about. Nothing is created until that second step
//   resolves — "Create" makes the channel and launches the context.md plan
//   session seeded by the description, "Skip" makes the channel alone. Either
//   way the user lands in the channel's feed, whose intro card carries the
//   onboarding (and offers context.md later if skipped).
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
  // Create mode's step. Describe mode has no name step, so it starts past it.
  const [step, setStep] = useState<"name" | "describe" | "repositories">(
    "name",
  );
  const descriptionHelperId = useId();

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
      const channel = await createChannel(trimmedName);
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
    if (canDescribe) setStep("repositories");
  };

  const descriptionField = (
    <Field>
      {/* In create mode the nested dialog's title asks the question, so the
          label would just repeat it. */}
      {isDescribeMode && (
        <>
          <FieldLabel htmlFor="context-description">
            What's this {spacesLayout ? "space" : "channel"} about?
          </FieldLabel>
          <FieldDescription id={descriptionHelperId}>
            Tell PostHog about this {spacesLayout ? "space" : "channel"}. We'll
            use it to create a CONTEXT.md file with relevant information for
            future tasks.
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

  // Describe mode is only ever the one dialog — the channel already exists, so
  // there's no name step to nest under.
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

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!busy) onOpenChange(next);
      }}
    >
      {/* quill stacks a nested dialog by pushing the *parent* down, which would
          leave step one peeking below step two. Invert it: pin this step at the
          base gap and drop step two below it (see its content), so the stack
          reads first-on-top. Inline style because these are CSS variables. */}
      <DialogContent
        showCloseButton={false}
        className="sm:max-w-lg"
        style={{ "--quill-dialog-top-gap": "max(1rem, 10vh)" } as CSSProperties}
      >
        <DialogHeader>
          <DialogTitle>
            Create a {spacesLayout ? "space" : "channel"}
          </DialogTitle>
        </DialogHeader>

        <DialogBody className="flex flex-col gap-4">
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
                  if (canAdvance) setStep("describe");
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
            onClick={() => setStep("describe")}
          >
            Next
          </Button>
        </DialogFooter>

        {/* The About dialog stays mounted behind the repository step so Quill
            can preserve the visual stack and return path. */}
        <Dialog
          open={step === "describe" || step === "repositories"}
          onOpenChange={(next) => {
            if (!busy && !next) setStep("name");
          }}
        >
          <DialogContent
            showCloseButton={false}
            className="sm:max-w-lg"
            // Sits below the name step, whose scaled-down top edge stays visible
            // above this one.
            style={
              {
                "--quill-dialog-top-gap": "max(1rem, 10vh + 1.5rem)",
              } as CSSProperties
            }
          >
            <DialogHeader>
              <DialogTitle>
                What's this {spacesLayout ? "space" : "channel"} about?
              </DialogTitle>
              <DialogDescription id={descriptionHelperId}>
                Tell PostHog about this {spacesLayout ? "space" : "channel"}.
                We'll use it to create a CONTEXT.md file with relevant
                information for future tasks.
              </DialogDescription>
            </DialogHeader>

            <DialogBody viewportClassName="flex flex-col gap-4">
              {descriptionField}
            </DialogBody>

            <DialogFooter>
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => setStep("name")}
              >
                Back
              </Button>
              <Button
                variant="default"
                disabled={busy}
                onClick={() => {
                  setDescription("");
                  setStep("repositories");
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

            <Dialog
              open={step === "repositories"}
              onOpenChange={(next) => {
                if (!busy && !next) setStep("describe");
              }}
            >
              <DialogContent
                showCloseButton={false}
                className="sm:max-w-lg"
                style={
                  {
                    "--quill-dialog-top-gap": "max(1rem, 10vh + 3rem)",
                  } as CSSProperties
                }
              >
                <DialogHeader>
                  <DialogTitle>Link repositories</DialogTitle>
                </DialogHeader>

                <DialogBody viewportClassName="flex flex-col gap-3">
                  <Text size="sm" variant="muted">
                    New tasks in this {spacesLayout ? "space" : "channel"} can
                    use these repositories. You can change them later.
                  </Text>
                  <RepositoriesField
                    selected={repositories}
                    integrationId={repositoryIntegration}
                    disabled={busy}
                    onChange={(nextRepositories, nextIntegration) => {
                      setRepositories(nextRepositories);
                      setRepositoryIntegration(nextIntegration);
                    }}
                  />
                </DialogBody>

                <DialogFooter>
                  <Button
                    variant="outline"
                    disabled={busy}
                    onClick={() => setStep("describe")}
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
              </DialogContent>
            </Dialog>
          </DialogContent>
        </Dialog>
      </DialogContent>
    </Dialog>
  );
}
