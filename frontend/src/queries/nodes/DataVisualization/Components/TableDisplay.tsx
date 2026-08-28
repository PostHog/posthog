import { useActions, useValues } from 'kea'

import { LemonSelect, LemonSelectProps } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { ChartDisplayType } from '~/types'

import { dataVisualizationLogic } from '../dataVisualizationLogic'
import { getTableDisplayOptions, renderDisplayTypeLabel } from './tableDisplayOptions'

interface TableDisplayProps extends Pick<LemonSelectProps<ChartDisplayType>, 'disabledReason'> {}

export const TableDisplay = ({ disabledReason }: TableDisplayProps): JSX.Element => {
    const { setVisualizationType } = useActions(dataVisualizationLogic)
    const { autoVisualizationType, columns, numericalColumns, visualizationType } = useValues(dataVisualizationLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <LemonSelect
            disabledReason={disabledReason}
            value={visualizationType}
            renderButtonContent={() => renderDisplayTypeLabel(visualizationType, autoVisualizationType)}
            onChange={(value) => {
                setVisualizationType(value)
            }}
            dropdownPlacement="bottom-end"
            optionTooltipPlacement="left"
            dropdownMatchSelectWidth={false}
            data-attr="chart-filter"
            options={getTableDisplayOptions(
                columns,
                numericalColumns,
                autoVisualizationType,
                undefined,
                !!featureFlags[FEATURE_FLAGS.SQL_BOX_PLOT_INSIGHT]
            )}
            size="small"
        />
    )
}
