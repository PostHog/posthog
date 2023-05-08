import { LemonTag } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { cohortsModel } from '~/models/cohortsModel'
import { FilterType } from '~/types'
import { breakdownTagLogic } from './breakdownTagLogic'
import { isAllCohort, isCohort, isPersonEventOrGroup } from './taxonomicBreakdownFilterUtils'
import { BreakdownTagMenu } from './BreakdownTagMenu'

type BreakdownTagProps = {
    breakdown: string | number
    filters: FilterType
    setFilters?: (filter: Partial<FilterType>, mergeFilters?: boolean) => void
}

export function BreakdownTag({ breakdown, filters, setFilters }: BreakdownTagProps): JSX.Element {
    const { cohortsById } = useValues(cohortsModel)

    const logicProps = { breakdown, filters, setFilters }
    const { isViewOnly, shouldShowMenu } = useValues(breakdownTagLogic(logicProps))
    const { removeBreakdown } = useActions(breakdownTagLogic(logicProps))

    return (
        <BindLogic logic={breakdownTagLogic} props={logicProps}>
            <LemonTag
                className="taxonomic-breakdown-filter tag-pill"
                // display remove button only if we can edit and don't have a separate menu
                closable={!isViewOnly && !shouldShowMenu}
                onClose={removeBreakdown}
                popover={{
                    overlay: shouldShowMenu ? <BreakdownTagMenu filters={filters} /> : undefined,
                    closeOnClickInside: false,
                }}
            >
                <>
                    {isPersonEventOrGroup(breakdown) && <PropertyKeyInfo value={breakdown} />}
                    {isAllCohort(breakdown) && <PropertyKeyInfo value={'All Users'} />}
                    {isCohort(breakdown) && (
                        <PropertyKeyInfo value={cohortsById[breakdown]?.name || `Cohort ${breakdown}`} />
                    )}
                </>
            </LemonTag>
        </BindLogic>
    )
}
