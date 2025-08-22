import { LemonButton } from 'lib/lemon-ui/LemonButton'

export function CohortSaveButton({
    cohortChanged,
    cohortLoading,
    isCalculating,
    isNewCohort,
}: {
    cohortChanged: boolean
    cohortLoading: boolean
    isCalculating: boolean
    isNewCohort: boolean
}): JSX.Element {
    const disabled = !isNewCohort && !cohortChanged

    return (
        <LemonButton
            type="primary"
            data-attr="save-cohort"
            htmlType="submit"
            disabled={disabled}
            loading={cohortLoading || isCalculating}
            form="cohort"
        >
            {disabled ? 'No changes' : 'Save'}
        </LemonButton>
    )
}
