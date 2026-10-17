import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal } from '@posthog/lemon-ui'

import { COHORT_CSV_HELP, CohortCsvDropzone } from './CohortCsvDropzone'
import { CohortLogicProps, cohortEditLogic } from './cohortEditLogic'

export function CohortCsvUploadModal({ id }: CohortLogicProps): JSX.Element {
    const logic = cohortEditLogic({ id })
    const { cohort, cohortErrors, cohortLoading, csvUploadModalOpen } = useValues(logic)
    const { setCohortValue, setCsvUploadModalOpen, uploadCohortCsv } = useActions(logic)

    const onClose = (): void => {
        if (!cohortErrors.name) {
            setCohortValue('csv', undefined)
        }
        setCsvUploadModalOpen(false)
    }

    const onCancel = (): void => {
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
                        onClick={onCancel}
                        disabledReason={cohortLoading ? 'Uploading the CSV' : undefined}
                        data-attr="cohort-upload-csv-modal-cancel"
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => uploadCohortCsv()}
                        loading={cohortLoading}
                        disabledReason={!cohort.csv ? 'Choose a CSV file first' : undefined}
                        data-attr="cohort-upload-csv-modal-save"
                    >
                        Upload
                    </LemonButton>
                </>
            }
        >
            {cohortErrors.name && <LemonBanner type="error">{cohortErrors.name}</LemonBanner>}
            <div className="ph-ignore-input">
                <CohortCsvDropzone
                    value={cohort.csv ?? null}
                    onChange={(file) => setCohortValue('csv', file ?? undefined)}
                />
            </div>
        </LemonModal>
    )
}
