import {
  normalizeChannelName,
  normalizeChannelNameInput,
  validateChannelName,
} from "@posthog/core/canvas/channelName";
import {
  emptySpaceSetupDraft,
  type SpaceSetupDraft,
  spaceSetupDraftMissingField,
  spaceSetupDraftToInput,
  spaceSetupNeedsRepository,
} from "@posthog/core/canvas/spaceSetup";
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
import { SPACE_SETUP_FLAG } from "@posthog/shared";
import {
  ANALYTICS_EVENTS,
  type ChannelsSurface,
} from "@posthog/shared/analytics-events";
import type { SpaceSetupInput, UserBasic } from "@posthog/shared/domain-types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import {
  type CreateStep,
  type CreateStepContext,
  createStepDirection,
  nextCreateStep,
  previousCreateStep,
} from "@posthog/ui/features/canvas/components/createChannelSteps";
import { MemberList } from "@posthog/ui/features/canvas/components/MemberList";
import { MemberSearch } from "@posthog/ui/features/canvas/components/MemberSearch";
import { SpaceFeatureFields } from "@posthog/ui/features/canvas/components/spaceSetup/SpaceFeatureFields";
import { SpaceGoalFields } from "@posthog/ui/features/canvas/components/spaceSetup/SpaceGoalFields";
import { SpaceSetupChoiceField } from "@posthog/ui/features/canvas/components/spaceSetup/SpaceSetupChoiceField";
import { SpaceSetupRetryDialog } from "@posthog/ui/features/canvas/components/spaceSetup/SpaceSetupRetryDialog";
import { useChannelMutations } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useGenerateContext } from "@posthog/ui/features/canvas/hooks/useGenerateContext";
import { useOrgMembers } from "@posthog/ui/features/canvas/hooks/useOrgMembers";
import { useSetupSpace } from "@posthog/ui/features/canvas/hooks/useSetupSpace";
import { useUpdateTaskChannelRepositories } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { RepositoriesField } from "@posthog/ui/features/integrations/components/RepositoriesField";
import { AnimatedHeight } from "@posthog/ui/primitives/AnimatedHeight";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useNavigate } from "@tanstack/react-router";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useEffect, useId, useMemo, useRef, useState } from "react";

const MAX_CONTEXT_NAME_LENGTH = 80;

const DESCRIPTION_EXAMPLES = [
  "Feature flags help teams control feature access, target specific users, and manage gradual rollouts.",
  "The onboarding experience guides new customers from creating an account to completing their first successful setup.",
  "We're migrating our billing system to Stripe while preserving existing subscriptions and minimizing disruption.",
  "Authentication includes sign-in, account recovery, session management, roles, and permissions across our applications.",
  "The mobile redesign aims to simplify navigation, improve accessibility, and make common workflows faster.",
];

const DESCRIPTION_ROTATION_INTERVAL_MS = 5000;

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
  surface?: ChannelsSurface;
}

export function CreateChannelModal({
  open,
  onOpenChange,
  existingContext,
  surface = "sidebar",
}: CreateChannelModalProps) {
  const isDescribeMode = !!existingContext;
  const spacesLayout = useChannelsLayout();
  const { createChannel, isCreating } = useChannelMutations();
  const { generate, isStarting } = useGenerateContext();
  const { setup, isStarting: isSettingUp } = useSetupSpace();
  // Dev builds default the step on, like the spaces layout, so it can be tried
  // without flag plumbing; force it off with the ph-dev-flags-off kill switch.
  const setupEnabled = useFeatureFlag(SPACE_SETUP_FLAG, import.meta.env.DEV);
  const linkRepositories = useUpdateTaskChannelRepositories();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [repositories, setRepositories] = useState<string[]>([]);
  const [repositoryIntegration, setRepositoryIntegration] = useState<
    number | null
  >(null);
  const [star, setStar] = useState(true);
  const [visibility, setVisibility] = useState<"public" | "private">("public");
  const [memberIds, setMemberIds] = useState<number[]>([]);
  const [setupDraft, setSetupDraft] =
    useState<SpaceSetupDraft>(emptySpaceSetupDraft);
  const [failedSetup, setFailedSetup] = useState<{
    channelId: string;
    input: SpaceSetupInput;
    error: string;
  } | null>(null);
  const authClient = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client: authClient });
  const { members: orgMembers } = useOrgMembers();
  const selectedMembers = useMemo(
    () =>
      memberIds
        .map((id) => orgMembers.find((member) => member.id === id))
        .filter((member): member is UserBasic => !!member),
    [memberIds, orgMembers],
  );
  const memberSearchExcludes = currentUser
    ? [...memberIds, currentUser.id]
    : memberIds;
  const [step, setStep] = useState<CreateStep>("name");
  const [direction, setDirection] = useState(1);
  const descriptionHelperId = useId();
  const reduceMotion = useReducedMotion();
  const stepDuration = reduceMotion ? 0 : STEP_DURATION;

  const stepContext: CreateStepContext = {
    setupEnabled,
    choice: setupDraft.choice,
    visibility,
  };

  const goToStep = (next: CreateStep | null) => {
    if (!next) return;
    setDirection(createStepDirection(step, next));
    setStep(next);
  };
  const goBack = () => goToStep(previousCreateStep(step, stepContext));
  const goForward = () => goToStep(nextCreateStep(step, stepContext));

  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open && !failedSetup) {
      setName("");
      setDescription("");
      setRepositories([]);
      setRepositoryIntegration(null);
      setStar(true);
      setVisibility("public");
      setMemberIds([]);
      setSetupDraft(emptySpaceSetupDraft());
      setStep("name");
    }
  }

  const trimmedName = normalizeChannelName(name);
  const trimmedDescription = description.trim();
  const remaining = MAX_CONTEXT_NAME_LENGTH - name.length;
  const nameError = isDescribeMode ? null : validateChannelName(trimmedName);

  const busy =
    isCreating || isStarting || isSettingUp || linkRepositories.isPending;
  const canAdvance = !busy && !!trimmedName && !nameError;
  const canDescribe = !busy && !!trimmedDescription;
  const setupMissingField = spaceSetupDraftMissingField(setupDraft);
  const repositoryMissing =
    setupEnabled &&
    spaceSetupNeedsRepository(setupDraft) &&
    repositories.length === 0;
  const canCreate = canAdvance && !repositoryMissing;

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

  const openSpace = (channelId: string): void => {
    setFailedSetup(null);
    onOpenChange(false);
    void navigate({ to: "/spaces/$channelId", params: { channelId } });
  };

  const startSetup = async (
    channelId: string,
    input: SpaceSetupInput,
  ): Promise<boolean> => {
    try {
      await setup({ channelId, setup: input });
    } catch (error) {
      setFailedSetup({
        channelId,
        input,
        error: error instanceof Error ? error.message : String(error),
      });
      return false;
    }
    track(ANALYTICS_EVENTS.CONTEXT_ACTION, {
      action_type: "setup_started",
      channel_id: channelId,
      setup_kind: input.kind,
    });
    return true;
  };

  const submitCreate = async () => {
    let contextId: string;
    try {
      const channel = await createChannel(trimmedName, {
        star,
        channelType: visibility,
        memberIds: visibility === "private" ? memberIds : [],
      });
      track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
        action_type: "create",
        surface,
        channel_id: channel.id,
        success: true,
      });
      contextId = channel.id;
    } catch (error) {
      track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
        action_type: "create",
        surface,
        success: false,
      });
      toast.error(`Couldn't create ${spacesLayout ? "space" : "channel"}`, {
        description: error instanceof Error ? error.message : String(error),
      });
      return;
    }

    if (repositories.length > 0) {
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

    const setupInput = setupEnabled
      ? spaceSetupDraftToInput(setupDraft, repositories[0] ?? null)
      : null;
    if (setupInput) {
      if (!(await startSetup(contextId, setupInput))) return;
    } else if (trimmedDescription) {
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

    openSpace(contextId);
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
    if (canDescribe) goForward();
  };

  const aboutTitle = `What's this ${spacesLayout ? "space" : "channel"} about?`;
  const aboutBlurb = `Tell PostHog about this ${
    spacesLayout ? "space" : "channel"
  }. We'll use it to create a CONTEXT.md file with relevant information for future tasks.`;

  const descriptionTextarea = (
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
  );

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
      {descriptionTextarea}
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

  if (failedSetup) {
    return (
      <SpaceSetupRetryDialog
        open={open}
        onOpenChange={(next) => {
          if (!busy) onOpenChange(next);
        }}
        error={failedSetup.error}
        busy={busy}
        onOpenSpace={() => openSpace(failedSetup.channelId)}
        onRetry={() =>
          void submitOnce(async () => {
            if (await startSetup(failedSetup.channelId, failedSetup.input)) {
              openSpace(failedSetup.channelId);
            }
          })
        }
      />
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
                      if (canAdvance) goForward();
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
                onClick={goForward}
              >
                Next
              </Button>
            </DialogFooter>
          </>
        );
      case "setup":
        return (
          <>
            <DialogHeader>
              <DialogTitle>What is this space for?</DialogTitle>
              <DialogDescription>
                A goal or a feature gets a context page filled in for you. A
                goal also gets a tracking canvas and loops that work toward it.
              </DialogDescription>
            </DialogHeader>

            <DialogBody
              className="flex max-h-[60vh] flex-col"
              viewportClassName="flex flex-col gap-4"
            >
              <SpaceSetupChoiceField
                value={setupDraft.choice}
                disabled={busy}
                onChange={(choice) =>
                  setSetupDraft((draft) => ({ ...draft, choice }))
                }
              />
              <AnimatedHeight duration={stepDuration} ease={EASE_IN_OUT}>
                <div key={setupDraft.choice} className="flex flex-col gap-4">
                  {setupDraft.choice === "goal" && (
                    <SpaceGoalFields
                      value={setupDraft.goal}
                      disabled={busy}
                      onChange={(goal) =>
                        setSetupDraft((draft) => ({ ...draft, goal }))
                      }
                    />
                  )}
                  {setupDraft.choice === "feature" && (
                    <SpaceFeatureFields
                      value={setupDraft.feature}
                      disabled={busy}
                      onChange={(feature) =>
                        setSetupDraft((draft) => ({ ...draft, feature }))
                      }
                    />
                  )}
                  {setupDraft.choice === "none" && (
                    <Field>
                      <FieldLabel htmlFor="context-description">
                        Describe it
                      </FieldLabel>
                      {descriptionTextarea}
                      <FieldDescription id={descriptionHelperId}>
                        Optional. A description starts a task that writes the
                        context page.
                      </FieldDescription>
                    </Field>
                  )}
                </div>
              </AnimatedHeight>
            </DialogBody>

            <DialogFooter>
              <Button
                variant="outline"
                className="sm:mr-auto"
                disabled={busy}
                onClick={goBack}
              >
                Back
              </Button>
              <Button
                variant="primary"
                disabled={busy || setupMissingField !== null}
                onClick={goForward}
                data-attr="space-setup-next"
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
                onClick={goBack}
              >
                Back
              </Button>
              <Button
                variant="default"
                disabled={busy}
                onClick={() => {
                  setDescription("");
                  goForward();
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
                  <ItemTitle>
                    <Label htmlFor="context-private">
                      Private {spacesLayout ? "space" : "channel"}
                    </Label>
                  </ItemTitle>
                  <ItemDescription>
                    Only invited members can see it. Off means everyone in the
                    project can.
                  </ItemDescription>
                </ItemContent>
                <ItemActions>
                  <Switch
                    id="context-private"
                    checked={visibility === "private"}
                    disabled={busy}
                    onCheckedChange={(on) =>
                      setVisibility(on ? "private" : "public")
                    }
                  />
                </ItemActions>
              </Item>
              <Item variant="outline">
                <ItemContent>
                  <ItemTitle className="text-xs">Repositories</ItemTitle>
                  <ItemDescription>
                    New tasks in this {spacesLayout ? "space" : "channel"} can
                    use these repositories. You can change them later.
                  </ItemDescription>
                  {repositoryMissing && (
                    <FieldError>
                      A goal needs a repository. Its loops open pull requests
                      there.
                    </FieldError>
                  )}
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
                onClick={goBack}
              >
                Back
              </Button>
              <Button
                variant="primary"
                disabled={!canCreate}
                loading={busy}
                onClick={() => {
                  if (visibility === "private") {
                    goForward();
                  } else {
                    void submitOnce(submitCreate);
                  }
                }}
              >
                {visibility === "private" ? "Next" : "Create"}
              </Button>
            </DialogFooter>
          </>
        );
      case "members":
        return (
          <>
            <DialogHeader>
              <DialogTitle>Invite people</DialogTitle>
              <DialogDescription>
                Choose project members who can access this private{" "}
                {spacesLayout ? "space" : "channel"}. You already have access
                and can add people later.
              </DialogDescription>
            </DialogHeader>
            <div className="px-4 pt-4">
              <MemberSearch
                excludeIds={memberSearchExcludes}
                onPick={(id) => setMemberIds((ids) => [...ids, id])}
                disabled={busy}
                placeholder="Add people…"
              />
            </div>
            <DialogBody
              className="flex max-h-[50vh] flex-col"
              viewportClassName="flex flex-col"
            >
              <MemberList
                members={selectedMembers}
                currentUser={currentUser ?? null}
                disabled={busy}
                onRemove={(id) =>
                  setMemberIds((ids) =>
                    ids.filter((memberId) => memberId !== id),
                  )
                }
              />
            </DialogBody>
            <DialogFooter>
              <Button
                variant="outline"
                className="sm:mr-auto"
                disabled={busy}
                onClick={goBack}
              >
                Back
              </Button>
              <Button
                variant="primary"
                disabled={!canCreate}
                loading={busy}
                onClick={() => void submitOnce(submitCreate)}
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
        const previous = previousCreateStep(step, stepContext);
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
