import { useValues } from 'kea'

import { IconCalendar, IconFlag } from '@posthog/icons'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { MemberSelect } from 'lib/components/MemberSelect'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { cn } from 'lib/utils/css-classes'
import { INSIGHT_TYPE_OPTIONS } from 'scenes/saved-insights/SavedInsights'
import { SavedInsightFilters } from 'scenes/saved-insights/savedInsightsLogic'

import { InsightType, SavedInsightsTabs } from '~/types'

export function SavedInsightsFilters({
    filters,
    setFilters,
}: {
    filters: SavedInsightFilters
    setFilters: (filters: Partial<SavedInsightFilters>) => void
}): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { tab, createdBy, insightType, dateFrom, dateTo, search, hideFeatureFlagInsights } = filters

    const showPathsV2 = !!featureFlags[FEATURE_FLAGS.PATHS_V2]

    const insightTypeOptions = INSIGHT_TYPE_OPTIONS.filter((option) => {
        if (option.value === InsightType.PATHS_V2 && !showPathsV2) {
            return false
        }
        return true
    })

    return (
        <div className={cn('flex justify-between gap-2 items-center flex-wrap')}>
            <LemonInput
                type="search"
                placeholder="Search for insights"
                onChange={(value) => setFilters({ search: value })}
                value={search || ''}
            />
            <div className="flex items-center gap-2 flex-wrap">
                <div className="flex items-center gap-2">
                    <span>Type:</span>
                    <LemonSelect
                        size="small"
                        options={insightTypeOptions}
                        value={insightType}
                        onChange={(v?: string): void => setFilters({ insightType: v })}
                        dropdownMatchSelectWidth={false}
                        data-attr="insight-type"
                    />
                </div>
                <div className="flex items-center gap-2">
                    <span>Last modified:</span>
                    <DateFilter
                        disabled={false}
                        dateFrom={dateFrom}
                        dateTo={dateTo}
                        onChange={(fromDate, toDate) => setFilters({ dateFrom: fromDate, dateTo: toDate ?? undefined })}
                        makeLabel={(key) => (
                            <>
                                <IconCalendar />
                                <span className="hide-when-small"> {key}</span>
                            </>
                        )}
                    />
                </div>
                {tab !== SavedInsightsTabs.Yours ? (
                    <div className="flex items-center gap-2">
                        <span>Created by:</span>
                        <MemberSelect
                            value={createdBy === 'All users' ? null : createdBy}
                            onChange={(user) => setFilters({ createdBy: user?.id || 'All users' })}
                        />
                    </div>
                ) : null}
                <FeatureFlagInsightsToggle
                    hideFeatureFlagInsights={hideFeatureFlagInsights ?? undefined}
                    onToggle={(checked) => setFilters({ hideFeatureFlagInsights: checked })}
                />
            </div>
        </div>
    )
}

const FeatureFlagInsightsToggle = ({
    hideFeatureFlagInsights,
    onToggle,
}: {
    hideFeatureFlagInsights?: boolean
    onToggle: (checked: boolean) => void
}): JSX.Element => {
    return (
        <Tooltip
            title={
                <div>
                    <p>
                        PostHog automatically creates insights by default for feature flags to help you understand their
                        performance.
                    </p>
                    <p>Use this toggle to hide these auto-generated insights from your insights list.</p>
                </div>
            }
            placement="top"
        >
            <LemonButton
                icon={<IconFlag />}
                onClick={() => onToggle(!hideFeatureFlagInsights)}
                type="secondary"
                size="small"
            >
                Hide feature flag insights: <LemonSwitch checked={hideFeatureFlagInsights || false} className="ml-1" />
            </LemonButton>
        </Tooltip>
    )
}
