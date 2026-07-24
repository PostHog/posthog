import { validateChannelName } from "@posthog/core/canvas/channelName";
import {
  Button,
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Field,
  FieldError,
  FieldLabel,
  Input,
  Textarea,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useChannelMutations } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useGenerateContext } from "@posthog/ui/features/canvas/hooks/useGenerateContext";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useNavigate } from "@tanstack/react-router";
import { type CSSProperties, useRef, useState } from "react";

// Matches Slack's "Create a channel" naming constraint.
const MAX_CONTEXT_NAME_LENGTH = 80;

const DESCRIPTION_PLACEHOLDER =
  "Grab all files relating to X feature, get all relevant pull requests, in this X repo(s)";

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
  const { createChannel, isCreating } = useChannelMutations();
  const { generate, isStarting } = useGenerateContext();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  // Create mode's step. Describe mode has no name step, so it starts past it.
  const [step, setStep] = useState<"name" | "describe">("name");

  // Reset the fields each time the modal opens so a previous draft never
  // lingers. Adjusted inline during render (prev-prop comparison) rather than in
  // an effect, which would flash a stale value for one commit.
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setName("");
      setDescription("");
      setStep("name");
    }
  }

  const trimmedName = name.trim();
  const trimmedDescription = description.trim();
  const remaining = MAX_CONTEXT_NAME_LENGTH - name.length;
  const nameError = isDescribeMode ? null : validateChannelName(trimmedName);

  const busy = isCreating || isStarting;
  const canAdvance = !busy && !!trimmedName && !nameError;
  // "Create" seeds the plan session, so it needs the description; "Skip" is the
  // way through without one.
  const canDescribe = !busy && !!trimmedDescription;

  // `busy` only disables the buttons a render after the mutation starts, so a
  // double-click lands two creates before it applies — and folder creation is
  // not idempotent by path, so that is two channels of the same name. Latch
  // synchronously; the buttons stay the user-visible half of this.
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

  // Create the channel and land in its feed — the intro (name, creation line,
  // context.md card) and "joined" row there are derived from the channel row.
  // With a description, also launch the plan session that builds context.md.
  const submitCreate = async (withContextMd: boolean) => {
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
      toast.error("Couldn't create channel", {
        description: error instanceof Error ? error.message : String(error),
      });
      return;
    }

    if (withContextMd && trimmedDescription) {
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

  // The description step's primary action: seed context.md, for a channel that
  // already exists (describe mode) or one this dialog is about to create.
  const submitDescribeStep = async () => {
    if (!canDescribe) return;
    if (isDescribeMode) {
      await submitDescribe();
    } else {
      await submitCreate(true);
    }
  };

  const descriptionField = (
    <Field>
      {/* In create mode the nested dialog's title asks the question, so the
          label would just repeat it. */}
      {isDescribeMode && (
        <FieldLabel htmlFor="context-description">
          What's this channel about?
        </FieldLabel>
      )}
      <Textarea
        id="context-description"
        autoFocus
        rows={4}
        className="max-h-[40vh] overflow-y-auto"
        value={description}
        placeholder={DESCRIPTION_PLACEHOLDER}
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
          <DialogTitle>Create a channel</DialogTitle>
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

        {/* Step two, nested inside step one rather than replacing it: quill
            scales and dims a parent that has a nested dialog open, so the name
            step stays visible behind — the stack is the affordance that says
            there's another step. Dismissing it (Escape) returns here. */}
        <Dialog
          open={step === "describe"}
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
              <DialogTitle>What's this channel about?</DialogTitle>
            </DialogHeader>

            <DialogBody viewportClassName="flex flex-col gap-4">
              {descriptionField}
            </DialogBody>

            <DialogFooter>
              {/* Skip still creates the channel — it only forgoes the
                  context.md, which the channel's intro card offers later. */}
              <Button
                variant="default"
                disabled={busy}
                onClick={() => void submitOnce(() => submitCreate(false))}
              >
                Skip
              </Button>
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
      </DialogContent>
    </Dialog>
  );
}
