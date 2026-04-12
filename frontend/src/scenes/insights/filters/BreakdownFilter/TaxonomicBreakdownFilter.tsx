import { BindLogic, useActions, useValues } from 'kea'
import { ReactElement } from 'react'

import { IconGear, IconPencil } from '@posthog/icons'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Link } from 'lib/lemon-ui/Link'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { urls } from 'scenes/urls'

import { LemonButton } from '~/lib/lemon-ui/LemonButton'
import { LemonLabel } from '~/lib/lemon-ui/LemonLabel'
import { Popover } from '~/lib/lemon-ui/Popover'
import { BreakdownFilter } from '~/queries/schema/schema-general'
import { ChartDisplayType, InsightLogicProps } from '~/types'

import { EditableBreakdownTag } from './BreakdownTag'
import { GlobalBreakdownOptionsMenu } from './GlobalBreakdownOptionsMenu'
import { TaxonomicBreakdownButton } from './TaxonomicBreakdownButton'
import { TaxonomicBreakdownFilterLogicProps, taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'

const BREAKDOWN_DOCS_URL = 'https://posthog.com/docs/product-analytics/trends/breakdowns'
const COHORT_BREAKDOWN_DOCS_URL = 'https://posthog.com/docs/product-analytics/trends/breakdowns#cohorts-and-breakdowns'

export interface TaxonomicBreakdownFilterProps {
    insightProps: InsightLogicProps
    breakdownFilter?: BreakdownFilter | null
    display?: ChartDisplayType | null
    isTrends: boolean
    isFunnels: boolean
    disabledReason?: string
    updateBreakdownFilter: (breakdownFilter: BreakdownFilter) => void
    updateDisplay: (display: ChartDisplayType | undefined) => void
    showLabel?: boolean
    showInlineOptions?: boolean
    disablePropertyInfo?: boolean
    size?: 'small' | 'medium'
}

export function TaxonomicBreakdownFilter({
    insightProps,
    breakdownFilter,
    display,
    isTrends,
    isFunnels,
    disabledReason,
    updateBreakdownFilter,
    updateDisplay,
    showLabel = true,
    showInlineOptions = false,
    disablePropertyInfo,
    size = 'medium',
}: TaxonomicBreakdownFilterProps): JSX.Element {
    const logicProps: TaxonomicBreakdownFilterLogicProps = {
        insightProps,
        isTrends,
        isFunnels,
        display,
        breakdownFilter: breakdownFilter || {},
        updateBreakdownFilter,
        updateDisplay,
    }
    const {
        breakdownArray,
        addBreakdownDisabledReason,
        breakdownOptionsOpened,
        isMultipleBreakdownsEnabled,
        taxonomicBreakdownType,
    } = useValues(taxonomicBreakdownFilterLogic(logicProps))
    const { toggleBreakdownOptions } = useActions(taxonomicBreakdownFilterLogic(logicProps))
    const { hogQL, canEditInSqlEditor } = useValues(insightDataLogic(insightProps))

    const breakdownDocsUrl =
        taxonomicBreakdownType === TaxonomicFilterGroupType.CohortsWithAllUsers
            ? COHORT_BREAKDOWN_DOCS_URL
            : BREAKDOWN_DOCS_URL

    const composedDisabledReason = ((): ReactElement | string | undefined => {
        if (disabledReason) {
            return disabledReason
        }
        if (!addBreakdownDisabledReason) {
            return undefined
        }

        return (
            <span className="flex flex-col gap-1.5 not-italic">
                <span>
                    {addBreakdownDisabledReason}{' '}
                    <Link to={breakdownDocsUrl} target="_blank" className="not-italic font-semibold">
                        Read the docs
                    </Link>
                </span>
                {canEditInSqlEditor && (
                    <span>
                        Need more flexibility?{' '}
                        <Link
                            to={urls.sqlEditor({ query: hogQL ?? undefined })}
                            data-attr="breakdown-limit-edit-sql"
                            className="font-semibold inline-flex items-center gap-1"
                        >
                            <IconPencil />
                            Edit in SQL editor
                        </Link>
                    </span>
                )}
            </span>
        )
    })()

    const tags = breakdownArray.map((breakdown) =>
        typeof breakdown === 'object' ? (
            <EditableBreakdownTag
                key={breakdown.property}
                breakdown={breakdown.property}
                breakdownType={breakdown.type ?? 'event'}
                isTrends={isTrends}
                disablePropertyInfo={disablePropertyInfo}
                size={size}
            />
        ) : (
            <EditableBreakdownTag
                key={breakdown}
                breakdown={breakdown}
                breakdownType={breakdownFilter?.breakdown_type ?? 'event'}
                isTrends={isTrends}
                disablePropertyInfo={disablePropertyInfo}
                size={size}
            />
        )
    )

    return (
        <BindLogic logic={taxonomicBreakdownFilterLogic} props={logicProps}>
            {(showLabel || (!showInlineOptions && isMultipleBreakdownsEnabled)) && (
                <div className="flex items-center gap-2">
                    {showLabel && (
                        <LemonLabel info="Use breakdown to see the aggregation (total volume, active users, etc.) for each value of that property. For example, breaking down by Current URL with total volume will give you the event volume for each URL your users have visited.">
                            Breakdown by
                        </LemonLabel>
                    )}
                    {!showInlineOptions && isMultipleBreakdownsEnabled && (
                        <Popover
                            overlay={<GlobalBreakdownOptionsMenu />}
                            visible={breakdownOptionsOpened}
                            onClickOutside={() => toggleBreakdownOptions(false)}
                        >
                            <LemonButton
                                icon={<IconGear />}
                                size="small"
                                noPadding
                                onClick={() => toggleBreakdownOptions(!breakdownOptionsOpened)}
                            />
                        </Popover>
                    )}
                </div>
            )}
            <div className="flex flex-wrap gap-2 items-center">
                {tags}
                <TaxonomicBreakdownButton
                    disabledReason={composedDisabledReason}
                    disabledReasonInteractive={!!composedDisabledReason}
                    size={size}
                />
            </div>
            {showInlineOptions && isMultipleBreakdownsEnabled && (
                <div className="mt-2 border-t pt-2">
                    <GlobalBreakdownOptionsMenu />
                </div>
            )}
        </BindLogic>
    )
}
