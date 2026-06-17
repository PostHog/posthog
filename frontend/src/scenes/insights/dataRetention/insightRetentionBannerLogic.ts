import { connect, kea, key, path, props, selectors } from 'kea'

import { dayjs } from 'lib/dayjs'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { isDataVisualizationNode, isHogQLQuery } from '~/queries/utils'
import { InsightLogicProps } from '~/types'

import { dataRetentionBannerLogic } from './dataRetentionBannerLogic'
import type { insightRetentionBannerLogicType } from './insightRetentionBannerLogicType'

// Per-insight half of the retention warning: does this insight's range reach past the team's retention window?
// "All time" is treated as exceeding (it resolves to the earliest event, so a team with only recent data wouldn't
// otherwise trip it); every other range uses the resolved date range straight from the query response.
export const insightRetentionBannerLogic = kea<insightRetentionBannerLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'dataRetention', 'insightRetentionBannerLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [
            dataRetentionBannerLogic,
            ['warningEligible', 'retentionMonths'],
            insightDataLogic(props),
            ['insightData', 'query'],
            insightVizDataLogic(props),
            ['dateRange'],
        ],
    })),
    selectors({
        rangeExceedsRetention: [
            (s) => [s.dateRange, s.insightData, s.retentionMonths, s.query],
            (dateRange, insightData, retentionMonths, query): boolean => {
                if (!retentionMonths) {
                    return false
                }
                // SQL/HogQL insights can scan arbitrary history with no resolvable range, so warn whenever eligible.
                if (query && (isHogQLQuery(query) || (isDataVisualizationNode(query) && isHogQLQuery(query.source)))) {
                    return true
                }
                // "All time" is an unbounded intent: warn even when the team's data doesn't yet reach that far back.
                if (dateRange?.date_from === 'all') {
                    return true
                }
                const dateFrom = insightData?.resolved_date_range?.date_from
                if (!dateFrom) {
                    return false
                }
                return dayjs(dateFrom).isBefore(dayjs().subtract(retentionMonths, 'month'))
            },
        ],
        shouldShowBanner: [
            (s) => [s.warningEligible, s.rangeExceedsRetention],
            (warningEligible, rangeExceedsRetention): boolean => warningEligible && rangeExceedsRetention,
        ],
    }),
])
