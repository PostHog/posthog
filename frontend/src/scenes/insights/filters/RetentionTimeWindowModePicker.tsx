import { useActions, useValues } from 'kea'

import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { RETENTION_TIME_WINDOW_MODE_OPTIONS } from 'scenes/retention/constants'

import { RetentionFilter } from '~/queries/schema/schema-general'
import { insightLogic } from '~/scenes/insights/insightLogic'
import { insightVizDataLogic } from '~/scenes/insights/insightVizDataLogic'

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
