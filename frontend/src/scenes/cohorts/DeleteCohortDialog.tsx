import { useValues } from 'kea'

import { LemonBanner, LemonDialog } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'

import { CohortType } from '~/types'

import { cohortDeleteDialogLogic } from './cohortDeleteDialogLogic'
import { CohortUsedInList } from './CohortUsedInList'

interface DeleteCohortDialogProps {
    cohortId: CohortType['id']
    cohortName?: string | null
    onConfirm: () => void
    closeDialog: () => void
}

export function DeleteCohortDialog({
    cohortId,
    cohortName,
    onConfirm,
    closeDialog,
}: DeleteCohortDialogProps): JSX.Element {
    const { blockers, blockersLoading } = useValues(cohortDeleteDialogLogic({ cohortId: Number(cohortId) }))
    const label = cohortName ? `"${cohortName}"` : 'this cohort'

    return (
        <div className="flex flex-col gap-y-2" data-attr="cohort-delete-dialog">
            {blockersLoading ? (
                <div className="flex items-center gap-x-2">
                    <Spinner />
                    <span>Checking what uses this cohort…</span>
                </div>
            ) : blockers?.length ? (
                <>
                    <LemonBanner type="warning">
                        You can't delete {label} while these still use it. Remove it from each of them, then delete the
                        cohort.
                    </LemonBanner>
                    <div className="max-h-60 overflow-y-auto">
                        <CohortUsedInList sections={blockers} />
                    </div>
                </>
            ) : (
                <span>Are you sure you want to delete {label}?</span>
            )}
            <div className="flex justify-end gap-x-2 pt-2">
                <LemonButton type="tertiary" size="small" onClick={closeDialog}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="secondary"
                    status="danger"
                    size="small"
                    disabledReason={
                        blockersLoading
                            ? 'Checking what uses this cohort'
                            : blockers?.length
                              ? 'Remove the cohort from everything listed above first'
                              : undefined
                    }
                    onClick={() => {
                        onConfirm()
                        closeDialog()
                    }}
                    data-attr="cohort-delete-dialog-confirm"
                >
                    Delete
                </LemonButton>
            </div>
        </div>
    )
}

export function openDeleteCohortDialog({
    cohortId,
    cohortName,
    onConfirm,
}: Omit<DeleteCohortDialogProps, 'closeDialog'>): void {
    LemonDialog.open({
        title: 'Delete cohort?',
        primaryButton: null,
        secondaryButton: null,
        content: (closeDialog) => (
            <DeleteCohortDialog
                cohortId={cohortId}
                cohortName={cohortName}
                onConfirm={onConfirm}
                closeDialog={closeDialog}
            />
        ),
    })
}
