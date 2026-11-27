import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal } from '@posthog/lemon-ui'

import { COHORT_CSV_HELP, CohortCsvDropzone } from './CohortCsvDropzone'
import { CohortLogicProps, cohortEditLogic } from './cohortEditLogic'
import { cohortCsvTooLargeMessage } from './cohortUtils'

export function CohortCsvUploadModal({ id }: CohortLogicProps): JSX.Element {
    const logic = cohortEditLogic({ id })
    const { cohort, cohortLoading, csvUploadModalOpen, csvMaxBytes } = useValues(logic)
    const { setCohortValue, setCsvUploadModalOpen, uploadCohortCsv } = useActions(logic)

    const csvTooLarge = !!cohort.csv && cohort.csv.size > csvMaxBytes

    // The modal only opens for saved cohorts, where the upload sends the CSV alone,
    // so an abandoned file can always be dropped on close.
    const onClose = (): void => {
        setCohortValue('csv', undefined)
        setCsvUploadModalOpen(false)
    }

    return (
        <LemonModal
            title="Upload a CSV"
            description={<span className="max-w-prose">{COHORT_CSV_HELP}</span>}
            isOpen={csvUploadModalOpen}
            onClose={onClose}
            closable={!cohortLoading}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={onClose}
                        disabledReason={cohortLoading ? 'Uploading the CSV' : undefined}
                        data-attr="cohort-upload-csv-modal-cancel"
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => uploadCohortCsv()}
                        loading={cohortLoading}
                        disabledReason={
                            !cohort.csv
                                ? 'Choose a CSV file first'
                                : csvTooLarge
                                  ? cohortCsvTooLargeMessage(csvMaxBytes)
                                  : undefined
                        }
                        data-attr="cohort-upload-csv-modal-save"
                    >
                        Upload
                    </LemonButton>
                </>
            }
        >
            {csvTooLarge && <LemonBanner type="error">{cohortCsvTooLargeMessage(csvMaxBytes)}</LemonBanner>}
            <div className="ph-ignore-input">
                <CohortCsvDropzone
                    value={cohort.csv ?? null}
                    onChange={(file) => setCohortValue('csv', file ?? undefined)}
                />
            </div>
        </LemonModal>
    )
}
