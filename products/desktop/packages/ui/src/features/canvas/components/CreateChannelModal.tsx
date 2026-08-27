import {
  normalizeChannelName,
  normalizeChannelNameInput,
  validateChannelName,
} from "@posthog/core/canvas/channelName";
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
import { useChannelMutations } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useGenerateContext } from "@posthog/ui/features/canvas/hooks/useGenerateContext";
import { useUpdateTaskChannelRepositories } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { RepositoriesField } from "@posthog/ui/features/integrations/components/RepositoriesField";
import { AnimatedHeight } from "@posthog/ui/primitives/AnimatedHeight";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useNavigate } from "@tanstack/react-router";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useEffect, useId, useRef, useState } from "react";

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

const EASE_OUT: [number, number, number, number] = [0.215, 0.61, 0.355, 1];
const EASE_IN_OUT: [number, number, number, number] = [0.645, 0.045, 0.355, 1];
const STEP_DURATION = 0.2;
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
  existingContext?: { channelId: string; channelName: string };
}

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
  const [step, setStep] = useState<CreateStep>("name");
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

  const trimmedName = normalizeChannelName(name);
  const trimmedDescription = description.trim();
  const remaining = MAX_CONTEXT_NAME_LENGTH - name.length;
  const nameError = isDescribeMode ? null : validateChannelName(trimmedName);

  const busy = isCreating || isStarting || linkRepositories.isPending;
  const canAdvance = !busy && !!trimmedName && !nameError;
  const canDescribe = !busy && !!trimmedDescription;

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
      await generate({
        channelId: contextId,
        channelName: trimmedName,
        description: trimmedDescription,
      });
    }

    onOpenChange(false);
    void navigate({
      to: "/spaces/$channelId",
      params: { channelId: contextId },
    });
  };

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

    onOpenChange(false);
    void navigate({
      to: "/spaces/$channelId",
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

  const renderStep = () => {
    switch (step) {
      case "name":
        return (
          <>
            <DialogHeader>
              <DialogTitle>
                Create a {spacesLayout ? "space" : "channel"}
              </DialogTitle>
              <DialogDescription>
                Create a {spacesLayout ? "space" : "channel"} to keep related
                work and context together.
              </DialogDescription>
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
                  onChange={(e) =>
                    setName(normalizeChannelNameInput(e.target.value))
                  }
                  onBlur={() => setName(normalizeChannelName(name))}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      if (canAdvance) goToStep("describe");
                    }
                  }}
                />
                <FieldDescription>
                  Names use lowercase letters, numbers, and hyphens.
                </FieldDescription>
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

  const stepDirection = reduceMotion ? 0 : direction;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (busy || next) return;
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
