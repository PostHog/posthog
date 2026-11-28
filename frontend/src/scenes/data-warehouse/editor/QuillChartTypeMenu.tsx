import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import {
    getTableDisplayOptions,
    renderDisplayTypeLabel,
} from '~/queries/nodes/DataVisualization/Components/TableDisplay'
import { dataVisualizationLogic } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { ChartDisplayType } from '~/types'

/** Picks how the results are drawn. The same options as the Lemon TableDisplay select, as a quill menu. */
export function QuillChartTypeMenu({ disabledReason }: { disabledReason?: string }): JSX.Element {
    const { setVisualizationType } = useActions(dataVisualizationLogic)
    const { autoVisualizationType, columns, numericalColumns, visualizationType } = useValues(dataVisualizationLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const groups = getTableDisplayOptions(
        columns,
        numericalColumns,
        autoVisualizationType,
        undefined,
        !!featureFlags[FEATURE_FLAGS.METRIC_INSIGHT]
    )

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={<Button variant="outline" disabledReason={disabledReason} data-attr="chart-filter" />}
            >
                <span className="min-w-0 truncate">
                    {renderDisplayTypeLabel(visualizationType, autoVisualizationType)}
                </span>
                <IconChevronDown />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                <DropdownMenuRadioGroup
                    value={visualizationType}
                    onValueChange={(value) => setVisualizationType(value as ChartDisplayType)}
                >
                    {groups.map((group, index) =>
                        'options' in group ? (
                            <DropdownMenuGroup key={index}>
                                {index > 0 ? <DropdownMenuSeparator /> : null}
                                {'title' in group && group.title ? (
                                    <DropdownMenuLabel>{group.title}</DropdownMenuLabel>
                                ) : null}
                                {group.options.map((option) =>
                                    'value' in option ? (
                                        <DropdownMenuRadioItem
                                            key={String(option.value)}
                                            value={option.value}
                                            disabledReason={option.disabledReason}
                                        >
                                            {option.icon}
                                            {option.label}
                                        </DropdownMenuRadioItem>
                                    ) : null
                                )}
                            </DropdownMenuGroup>
                        ) : null
                    )}
                </DropdownMenuRadioGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
