import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonDivider,
    LemonInput,
    LemonModal,
    LemonSkeleton,
    Link,
} from '@posthog/lemon-ui'

import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { DELETE_CONFIRMATION_TEXT, personsBulkDeleteLogic } from './personsBulkDeleteLogic'

export function PersonsBulkDeleteModal(): JSX.Element {
    const {
        filters,
        matchCount,
        matchCountLoading,
        deleteEvents,
        deleteRecordings,
        confirmationText,
        isConfirmed,
        deletedCount,
        isDeleting,
    } = useValues(personsBulkDeleteLogic)
    const { closeModal, setDeleteEvents, setDeleteRecordings, setConfirmationText, deleteMatchingPersons } =
        useActions(personsBulkDeleteLogic)

    const nothingMatches = matchCount === 0

    return (
        <LemonModal
            isOpen={!!filters}
            onClose={isDeleting ? undefined : closeModal}
            title="Delete matching persons"
            maxWidth="560px"
        >
            <div className="space-y-4">
                <div className="space-y-2">
                    <p className="mb-0">
                        Every person matching the filters on this table will be deleted. This cannot be undone.
                    </p>
                    {filters?.search && (
                        <p className="mb-0">
                            Search: <strong>{filters.search}</strong>
                        </p>
                    )}
                    {!!filters?.properties.length && <PropertyFiltersDisplay filters={filters.properties} compact />}
                </div>

                {matchCountLoading ? (
                    <LemonSkeleton className="h-6 w-48" />
                ) : (
                    matchCount !== null && (
                        <h4 className="mb-0">
                            {matchCount.toLocaleString()} {matchCount === 1 ? 'person' : 'persons'} will be deleted.
                        </h4>
                    )
                )}

                <div className="space-y-2">
                    <LemonCheckbox
                        onChange={setDeleteEvents}
                        checked={deleteEvents}
                        disabled={isDeleting}
                        label="Also delete all of their events."
                        data-attr="bulk-delete-persons-with-events"
                    />
                    <LemonCheckbox
                        onChange={setDeleteRecordings}
                        checked={deleteRecordings}
                        disabled={isDeleting}
                        label="Also delete all of their recordings."
                        data-attr="bulk-delete-persons-with-recordings"
                    />
                </div>
                {(deleteEvents || deleteRecordings) && (
                    <LemonBanner type="warning">
                        Events and recordings are not removed right away. They are deleted on a set schedule during
                        non-peak usage times.{' '}
                        <Link to="https://posthog.com/docs/privacy/data-deletion" target="_blank" className="font-bold">
                            Learn more
                        </Link>
                    </LemonBanner>
                )}

                <LemonDivider />

                {isDeleting ? (
                    <div className="space-y-2">
                        <p className="mb-0">
                            Deleted {deletedCount.toLocaleString()}
                            {matchCount ? ` of ${matchCount.toLocaleString()}` : ''} so far. Keep this tab open until it
                            finishes.
                        </p>
                        <LemonProgress percent={matchCount ? Math.min(deletedCount / matchCount, 1) * 100 : 0} />
                    </div>
                ) : (
                    <div className="space-y-2">
                        <label className="text-sm">
                            To confirm, type <strong>{DELETE_CONFIRMATION_TEXT}</strong> below:
                        </label>
                        <LemonInput
                            value={confirmationText}
                            onChange={setConfirmationText}
                            placeholder={DELETE_CONFIRMATION_TEXT}
                            className="w-full"
                            autoFocus
                        />
                    </div>
                )}
            </div>
            <div className="flex justify-end gap-2 mt-4">
                <LemonButton
                    type="secondary"
                    onClick={closeModal}
                    disabledReason={isDeleting ? 'Deletion is in progress' : undefined}
                    data-attr="bulk-delete-persons-cancel"
                >
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    status="danger"
                    loading={isDeleting}
                    disabledReason={
                        isDeleting
                            ? 'Deletion is in progress'
                            : matchCountLoading
                              ? 'Counting the matching persons'
                              : nothingMatches
                                ? 'No persons match these filters'
                                : !isConfirmed
                                  ? `Type "${DELETE_CONFIRMATION_TEXT}" to confirm`
                                  : undefined
                    }
                    onClick={deleteMatchingPersons}
                    data-attr="bulk-delete-persons"
                >
                    {matchCount ? `Delete ${matchCount.toLocaleString()} persons` : 'Delete persons'}
                </LemonButton>
            </div>
        </LemonModal>
    )
}
