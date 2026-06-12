import { useActions, useValues } from 'kea'

import { insightVizDataLogic } from '@posthog/query-frontend/nodes/InsightViz/insightVizDataLogic'
import { RETENTION_TIME_WINDOW_MODE_OPTIONS } from '@posthog/query-frontend/nodes/RetentionQuery/constants'
import { RetentionFilter } from '@posthog/query-frontend/schema/schema-general'

import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { insightLogic } from 'scenes/insights/insightLogic'

export function RetentionTimeWindowModePicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const handleChange = (timeWindowMode?: RetentionFilter['timeWindowMode']): void => {
        updateInsightFilter({ timeWindowMode })
    }

    return (
        <LemonSelect
            value={retentionFilter?.timeWindowMode ?? 'strict_calendar_dates'}
            onChange={handleChange}
            options={RETENTION_TIME_WINDOW_MODE_OPTIONS}
            dropdownMatchSelectWidth={false}
        />
    )
}
