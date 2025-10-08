import { useActions, useValues } from 'kea'

import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { RETENTION_TIME_WINDOW_MODE_OPTIONS } from 'scenes/retention/constants'
import { retentionLogic } from 'scenes/retention/retentionLogic'

import { RetentionFilter } from '~/queries/schema/schema-general'
import { insightLogic } from '~/scenes/insights/insightLogic'

export function RetentionTimeWindowModePicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const logic = retentionLogic(insightProps)
    const { retentionFilter } = useValues(logic)
    const { setRetentionFilter } = useActions(logic)

    const handleChange = (timeWindowMode?: RetentionFilter['timeWindowMode']): void => {
        setRetentionFilter({ timeWindowMode })
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
