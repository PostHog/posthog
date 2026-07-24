import {
  ArrowClockwiseIcon,
  EyeSlashIcon,
  PauseIcon,
  TrashIcon,
  XIcon,
} from "@phosphor-icons/react";
import { isDismissalReasonSnooze } from "@posthog/shared/dismissalReasons";
import type { SignalReport } from "@posthog/shared/types";
import {
  DismissReportDialog,
  type DismissReportDialogResult,
} from "@posthog/ui/features/inbox/components/DismissReportDialog";
import { useInboxBulkActions } from "@posthog/ui/features/inbox/hooks/useInboxBulkActions";
import { Button } from "@posthog/ui/primitives/Button";
import { AlertDialog, Flex, Text } from "@radix-ui/themes";
import { useCallback, useState } from "react";

interface InboxBulkSelectionBarProps {
  reports: SignalReport[];
  selectedReportIds: string[];
  onClearSelection: () => void;
}

export function InboxBulkSelectionBar({
  reports,
  selectedReportIds,
  onClearSelection,
}: InboxBulkSelectionBarProps) {
  const bulkActions = useInboxBulkActions(reports, selectedReportIds);
  const [showSnoozeConfirm, setShowSnoozeConfirm] = useState(false);
  const [showSuppressConfirm, setShowSuppressConfirm] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [showDismissDialog, setShowDismissDialog] = useState(false);

  const selectedCount = bulkActions.selectedCount;
  const isMulti = selectedCount > 1;

  const handleConfirmSnooze = useCallback(async () => {
    const ok = await bulkActions.snoozeSelected();
    if (ok) setShowSnoozeConfirm(false);
  }, [bulkActions]);

  const handleConfirmSuppress = useCallback(async () => {
    const ok = await bulkActions.suppressSelected();
    if (ok) setShowSuppressConfirm(false);
  }, [bulkActions]);

  const handleConfirmDelete = useCallback(async () => {
    const ok = await bulkActions.deleteSelected();
    if (ok) setShowDeleteConfirm(false);
  }, [bulkActions]);

  const handleDismissConfirm = useCallback(
    async (result: DismissReportDialogResult) => {
      const isSnooze = isDismissalReasonSnooze(result.reason);
      const ok = isSnooze
        ? await bulkActions.snoozeSelected()
        : await bulkActions.suppressSelected(result);
      if (ok) setShowDismissDialog(false);
    },
    [bulkActions],
  );

  const dismissPending = bulkActions.isSuppressing || bulkActions.isSnoozing;

  if (selectedCount === 0) return null;

  return (
    <>
      <Flex
        align="center"
        justify="between"
        gap="3"
        wrap="wrap"
        className="rounded-(--radius-2) border border-(--accent-7) bg-(--accent-2) px-3 py-2"
      >
        <Flex align="center" gap="2" className="min-w-0">
          <Text className="shrink-0 font-medium text-[13px] text-gray-12">
            {selectedCount} selected
          </Text>
          <Text className="text-[12px] text-gray-10">
            Shift-click range · {"\u2318"}-click toggle · Esc to clear
          </Text>
        </Flex>

        <Flex align="center" gap="2" wrap="wrap">
          {isMulti ? (
            <>
              <Button
                type="button"
                size="1"
                variant="soft"
                color="gray"
                tooltipContent="Wait for selected reports to gather more context"
                disabledReason={bulkActions.snoozeDisabledReason}
                disabled={
                  bulkActions.snoozeDisabledReason !== null ||
                  bulkActions.isSnoozing
                }
                loading={bulkActions.isSnoozing}
                onClick={() => setShowSnoozeConfirm(true)}
              >
                <PauseIcon size={12} />
                Snooze
              </Button>
              <Button
                type="button"
                size="1"
                variant="soft"
                color="gray"
                tooltipContent="Permanently suppress selected reports"
                disabledReason={bulkActions.suppressDisabledReason}
                disabled={
                  bulkActions.suppressDisabledReason !== null ||
                  bulkActions.isSuppressing
                }
                loading={bulkActions.isSuppressing}
                onClick={() => setShowSuppressConfirm(true)}
              >
                <EyeSlashIcon size={12} />
                Suppress
              </Button>
            </>
          ) : (
            <Button
              type="button"
              size="1"
              variant="soft"
              color="gray"
              tooltipContent="Snooze or archive"
              disabledReason={bulkActions.suppressDisabledReason}
              disabled={
                bulkActions.suppressDisabledReason !== null || dismissPending
              }
              loading={dismissPending}
              onClick={() => setShowDismissDialog(true)}
            >
              Archive
            </Button>
          )}

          <Button
            type="button"
            size="1"
            variant="soft"
            color="gray"
            tooltipContent="Runs the signals pipeline again for each selected report"
            disabledReason={bulkActions.reingestDisabledReason}
            disabled={
              bulkActions.reingestDisabledReason !== null ||
              bulkActions.isReingesting
            }
            loading={bulkActions.isReingesting}
            onClick={() => void bulkActions.reingestSelected()}
          >
            <ArrowClockwiseIcon size={12} />
            Reingest
          </Button>

          <Button
            type="button"
            size="1"
            variant="soft"
            color="red"
            tooltipContent="Permanently delete selected reports and their signals"
            disabledReason={bulkActions.deleteDisabledReason}
            disabled={
              bulkActions.deleteDisabledReason !== null ||
              bulkActions.isDeleting
            }
            loading={bulkActions.isDeleting}
            onClick={() => setShowDeleteConfirm(true)}
          >
            <TrashIcon size={12} />
            Delete
          </Button>

          <Button
            type="button"
            size="1"
            variant="ghost"
            color="gray"
            aria-label="Clear selection"
            tooltipContent="Clear selection"
            onClick={onClearSelection}
          >
            <XIcon size={12} />
          </Button>
        </Flex>
      </Flex>

      <AlertDialog.Root
        open={showSnoozeConfirm}
        onOpenChange={setShowSnoozeConfirm}
      >
        <AlertDialog.Content maxWidth="420px">
          <AlertDialog.Title>Snooze reports</AlertDialog.Title>
          <AlertDialog.Description size="2">
            Selected reports will go back to gathering context. You can review
            them again once they are ready.
          </AlertDialog.Description>
          <Flex gap="3" mt="4" justify="end">
            <AlertDialog.Cancel>
              <Button variant="soft" color="gray">
                Cancel
              </Button>
            </AlertDialog.Cancel>
            <AlertDialog.Action>
              <Button
                variant="solid"
                color="gray"
                loading={bulkActions.isSnoozing}
                onClick={() => void handleConfirmSnooze()}
              >
                Snooze
              </Button>
            </AlertDialog.Action>
          </Flex>
        </AlertDialog.Content>
      </AlertDialog.Root>

      <AlertDialog.Root
        open={showSuppressConfirm}
        onOpenChange={setShowSuppressConfirm}
      >
        <AlertDialog.Content maxWidth="420px">
          <AlertDialog.Title>Suppress reports</AlertDialog.Title>
          <AlertDialog.Description size="2">
            Suppressing a report causes all future signals matched to that
            report to be ignored.
          </AlertDialog.Description>
          <Flex gap="3" mt="4" justify="end">
            <AlertDialog.Cancel>
              <Button variant="soft" color="gray">
                Cancel
              </Button>
            </AlertDialog.Cancel>
            <AlertDialog.Action>
              <Button
                variant="solid"
                color="orange"
                loading={bulkActions.isSuppressing}
                onClick={() => void handleConfirmSuppress()}
              >
                Suppress
              </Button>
            </AlertDialog.Action>
          </Flex>
        </AlertDialog.Content>
      </AlertDialog.Root>

      <AlertDialog.Root
        open={showDeleteConfirm}
        onOpenChange={setShowDeleteConfirm}
      >
        <AlertDialog.Content maxWidth="420px">
          <AlertDialog.Title>Delete reports</AlertDialog.Title>
          <AlertDialog.Description size="2">
            Permanently delete {selectedCount}{" "}
            {selectedCount === 1 ? "report" : "reports"} and their signals?
          </AlertDialog.Description>
          <Flex gap="3" mt="4" justify="end">
            <AlertDialog.Cancel>
              <Button variant="soft" color="gray">
                Cancel
              </Button>
            </AlertDialog.Cancel>
            <AlertDialog.Action>
              <Button
                variant="solid"
                color="red"
                loading={bulkActions.isDeleting}
                onClick={() => void handleConfirmDelete()}
              >
                Delete
              </Button>
            </AlertDialog.Action>
          </Flex>
        </AlertDialog.Content>
      </AlertDialog.Root>

      {showDismissDialog && bulkActions.selectedReports[0] ? (
        <DismissReportDialog
          open
          onOpenChange={setShowDismissDialog}
          report={bulkActions.selectedReports[0]}
          selectedCount={selectedCount}
          isSubmitting={dismissPending}
          snoozeDisabledReason={bulkActions.snoozeDisabledReason}
          onConfirm={handleDismissConfirm}
        />
      ) : null}
    </>
  );
}
