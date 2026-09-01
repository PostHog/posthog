import {
  DISMISSAL_REASON_OPTIONS,
  type DismissalReasonOptionValue,
  isDismissalReasonSnooze,
} from "@posthog/shared/dismissalReasons";
import type { SignalReport } from "@posthog/shared/types";
import { GitHubRepoPicker } from "@posthog/ui/features/folder-picker/GitHubRepoPicker";
import {
  ExplainedPauseLabel,
  ExplainedSuppressLabel,
} from "@posthog/ui/features/inbox/components/utils/ExplainedDismissOptionLabels";
import { useIntegrationSelectors } from "@posthog/ui/features/integrations/store";
import {
  useGithubRepositories,
  useIntegrations,
} from "@posthog/ui/features/integrations/useIntegrations";
import { Button } from "@posthog/ui/primitives/Button";
import { Dialog, Flex, RadioGroup, Text, TextArea } from "@radix-ui/themes";
import { useEffect, useRef, useState } from "react";

export interface DismissReportDialogResult {
  reason: DismissalReasonOptionValue;
  note: string;
  /** 'owner/repo' the reports should have targeted; only set when reason is 'wrong_repo'. */
  correctedRepository: string | null;
}

export interface DismissReportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  report: SignalReport;
  /** When greater than 1, copy reflects a bulk dismiss of the current selection. */
  selectedCount?: number;
  isSubmitting: boolean;
  /**
   * When snooze is not allowed for the current selection, the "Already fixed"
   * option is disabled because that path snoozes instead of dismissing.
   */
  snoozeDisabledReason: string | null;
  onConfirm: (result: DismissReportDialogResult) => void;
}

export function DismissReportDialog({
  open,
  onOpenChange,
  report,
  selectedCount = 1,
  isSubmitting,
  snoozeDisabledReason,
  onConfirm,
}: DismissReportDialogProps) {
  const onOpenChangeRef = useRef(onOpenChange);
  onOpenChangeRef.current = onOpenChange;

  // Quill's combobox portals its popup to document.body, outside Dialog.Content, so Radix
  // treats clicks on the popup as "outside the dialog". While the picker is open, every
  // dismiss path below must close only the popup. Otherwise selecting a repository closes
  // the whole dialog and drops the reason and note already entered.
  const [isRepoPickerOpen, setIsRepoPickerOpen] = useState(false);

  useEffect(() => {
    if (!open) setIsRepoPickerOpen(false);
  }, [open]);

  // Radix Themes nests Content inside the overlay scroll area, so backdrop clicks
  // often land on padding/overlay nodes that never reach Content's dismiss layer.
  useEffect(() => {
    if (!open || isSubmitting || isRepoPickerOpen) return;

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;

      const overlay = document.querySelector(
        '.rt-DialogOverlay[data-state="open"]',
      );
      const content = document.querySelector(
        '.rt-DialogContent[data-state="open"]',
      );
      if (!overlay?.contains(target) || content?.contains(target)) return;

      onOpenChangeRef.current(false);
    };

    document.addEventListener("pointerdown", handlePointerDown, true);
    return () =>
      document.removeEventListener("pointerdown", handlePointerDown, true);
  }, [open, isSubmitting, isRepoPickerOpen]);

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Content
        maxWidth="480px"
        onPointerDownOutside={(event) => {
          // preventDefault, not just skipping onOpenChange: Radix also dismisses a controlled
          // dialog through Root's own onOpenChange unless the event is cancelled.
          if (isSubmitting || isRepoPickerOpen) {
            event.preventDefault();
            return;
          }
          onOpenChange(false);
        }}
        onEscapeKeyDown={(event) => {
          if (isSubmitting || isRepoPickerOpen) {
            event.preventDefault();
            return;
          }
          onOpenChange(false);
        }}
      >
        <DismissReportDialogBody
          report={report}
          selectedCount={selectedCount}
          isSubmitting={isSubmitting}
          snoozeDisabledReason={snoozeDisabledReason}
          onConfirm={onConfirm}
          isRepoPickerOpen={isRepoPickerOpen}
          onRepoPickerOpenChange={setIsRepoPickerOpen}
        />
      </Dialog.Content>
    </Dialog.Root>
  );
}

function DismissReportDialogBody({
  report,
  selectedCount,
  isSubmitting,
  snoozeDisabledReason,
  onConfirm,
  isRepoPickerOpen,
  onRepoPickerOpenChange,
}: Omit<DismissReportDialogProps, "open" | "onOpenChange"> & {
  selectedCount: number;
  /** Owned by the dialog wrapper, which suppresses its dismiss paths while the picker is open. */
  isRepoPickerOpen: boolean;
  onRepoPickerOpenChange: (open: boolean) => void;
}) {
  const [reason, setReason] = useState<DismissalReasonOptionValue | null>(null);
  const [note, setNote] = useState("");
  const [correctedRepository, setCorrectedRepository] = useState<string | null>(
    null,
  );
  const [repoSearch, setRepoSearch] = useState("");

  const isWrongRepo = reason === "wrong_repo";
  // Populates the integration store in case no other surface loaded it yet; react-query dedupes.
  useIntegrations();
  const { hasGithubIntegration } = useIntegrationSelectors();
  // Enabled on the reason alone, not on isRepoPickerOpen: when the list is empty the picker
  // renders a disabled "No GitHub repos" trigger that cannot be opened, so gating the fetch on
  // the open state would deadlock on a cold cache (never open -> never fetch -> never open).
  const repoPage = useGithubRepositories(repoSearch, isWrongRepo);

  const handleConfirm = () => {
    if (!reason) return;
    onConfirm({
      reason,
      note: note.trim(),
      // A correction picked and then abandoned for another reason must not ride along.
      correctedRepository: isWrongRepo ? correctedRepository : null,
    });
  };

  const alreadyFixedDisabled = snoozeDisabledReason !== null;
  const pausesReport = reason != null && isDismissalReasonSnooze(reason);
  const reportNoun = selectedCount > 1 ? "reports" : "report";

  return (
    <>
      <Dialog.Title>
        <Text className="text-balance font-bold text-lg">
          {pausesReport
            ? selectedCount > 1
              ? `Pause ${selectedCount} reports?`
              : `Pause report "${report.title?.trim() ? report.title : "Untitled report"}"?`
            : selectedCount > 1
              ? `Archive ${selectedCount} reports for everyone?`
              : `Archive report "${report.title?.trim() ? report.title : "Untitled report"}" for everyone?`}
        </Text>
      </Dialog.Title>
      <Dialog.Description className="text-gray-10 text-sm">
        {pausesReport
          ? `This pauses the ${reportNoun} for everyone in this project until another matching signal arrives. The ${reportNoun} can then return.`
          : `This archives the ${reportNoun} for everyone in this project. Your feedback is saved and helps the agent.`}
      </Dialog.Description>

      <Flex direction="column" gap="4" mt="4">
        <RadioGroup.Root
          size="1"
          value={reason ?? ""}
          onValueChange={(value) =>
            setReason(value as DismissalReasonOptionValue)
          }
        >
          <Flex direction="column" gap="2">
            {DISMISSAL_REASON_OPTIONS.map((option) => {
              const snoozesInsteadOfDismiss = isDismissalReasonSnooze(
                option.value,
              );
              const disabled = snoozesInsteadOfDismiss && alreadyFixedDisabled;

              return snoozesInsteadOfDismiss ? (
                <ExplainedPauseLabel
                  key={option.value}
                  label={option.label}
                  value={option.value}
                  disabled={disabled}
                  disabledReason={disabled ? snoozeDisabledReason : undefined}
                />
              ) : (
                <ExplainedSuppressLabel
                  key={option.value}
                  label={option.label}
                  value={option.value}
                />
              );
            })}
          </Flex>
        </RadioGroup.Root>

        {isWrongRepo && hasGithubIntegration ? (
          <div className="flex flex-col gap-1">
            <span className="text-(--gray-12) text-xs">
              Which repository should it have been?
            </span>
            <GitHubRepoPicker
              value={correctedRepository}
              onChange={setCorrectedRepository}
              repositories={repoPage.repositories}
              isLoading={repoPage.isPending}
              isLoadingMore={repoPage.isFetchingMore}
              open={isRepoPickerOpen}
              onOpenChange={onRepoPickerOpenChange}
              searchQuery={repoSearch}
              onSearchQueryChange={setRepoSearch}
              hasMore={repoPage.hasMore}
              onLoadMore={repoPage.loadMore}
              disabled={isSubmitting}
              placeholder="Search repositories"
              size="1"
            />
            <span className="text-(--gray-10) text-xs">
              Optional. The agent uses your correction when picking repositories
              in the future.
            </span>
          </div>
        ) : null}

        <TextArea
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="Optional: add detail"
          size="1"
          rows={3}
          maxLength={4000}
          disabled={isSubmitting}
        />
      </Flex>

      <Flex gap="3" mt="4" justify="end">
        <Dialog.Close>
          <Button variant="soft" color="gray">
            Cancel
          </Button>
        </Dialog.Close>
        <Button
          variant="solid"
          disabled={!reason || isSubmitting}
          disabledReason={!reason ? "you haven't picked a reason" : null}
          onClick={handleConfirm}
          loading={isSubmitting}
        >
          {pausesReport ? "Pause for everyone" : "Archive for everyone"}
        </Button>
      </Flex>
    </>
  );
}
