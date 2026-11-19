import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonColorButton, LemonColorPicker, LemonInput, LemonLabel, Popover } from '@posthog/lemon-ui'

import { DataColorToken, getSeriesColor } from 'lib/colors'
import { dataThemeLogic } from 'scenes/dataThemeLogic'

import { ResultCustomizationBy } from '~/queries/schema/schema-general'

import { dataVisualizationLogic } from '../dataVisualizationLogic'
import { AxisBreakdownSeries } from './seriesBreakdownLogic'

export const BreakdownSeries = ({
    series,
    index,
}: {
    series: AxisBreakdownSeries<number | null>
    index: number
}): JSX.Element => {
    const [settingsOpen, setSettingsOpen] = useState(false)
    const { chartSettings } = useValues(dataVisualizationLogic)
    const { updateChartSettings } = useActions(dataVisualizationLogic)
    const { getTheme } = useValues(dataThemeLogic)

    const theme = getTheme(undefined)
    const themeTokens = theme ? (Object.keys(theme) as DataColorToken[]) : []
    const customization = chartSettings.resultCustomizations?.[series.breakdownValue]
    const selectedToken = customization?.customColor ? null : (customization?.color ?? null)
    const seriesColor = series.settings?.display?.color ?? getSeriesColor(index)

    return (
        <div className="flex gap-1 mb-2 items-center">
            <LemonColorPicker
                colorTokens={themeTokens}
                selectedColorToken={selectedToken}
                customButton={<LemonColorButton type="tertiary" color={seriesColor} className="mr-2" />}
                showCustomColor
                customColorValue={chartSettings.resultCustomizations?.[series.breakdownValue]?.customColor}
                onSelectCustomColor={(customColor) =>
                    updateChartSettings({
                        resultCustomizations: {
                            ...chartSettings.resultCustomizations,
                            [series.breakdownValue]: {
                                ...chartSettings.resultCustomizations?.[series.breakdownValue],
                                assignmentBy: ResultCustomizationBy.Value,
                                customColor,
                            },
                        },
                    })
                }
                onSelectColorToken={(token) => {
                    updateChartSettings({
                        resultCustomizations: {
                            ...chartSettings.resultCustomizations,
                            [series.breakdownValue]: {
                                ...chartSettings.resultCustomizations?.[series.breakdownValue],
                                assignmentBy: ResultCustomizationBy.Value,
                                color: token,
                                customColor: undefined,
                            },
                        },
                    })
                }}
                onClearColorToken={() => {
                    updateChartSettings({
                        resultCustomizations: {
                            ...chartSettings.resultCustomizations,
                            [series.breakdownValue]: {
                                ...customization,
                                assignmentBy: ResultCustomizationBy.Value,
                                color: undefined,
                                customColor: undefined,
                            },
                        },
                    })
                }}
            />
            <span className="flex-1 truncate">{series.settings?.display?.label || series.name || '[No value]'}</span>
            <Popover
                visible={settingsOpen}
                onClickOutside={() => setSettingsOpen(false)}
                overlay={
                    <div className="p-2 w-64">
                        <LemonLabel className="mb-1">Label</LemonLabel>
                        <LemonInput
                            aria-label="Breakdown label"
                            value={customization?.label ?? ''}
                            placeholder={series.name}
                            onChange={(label) => {
                                updateChartSettings({
                                    resultCustomizations: {
                                        ...chartSettings.resultCustomizations,
                                        [series.breakdownValue]: {
                                            ...customization,
                                            assignmentBy: ResultCustomizationBy.Value,
                                            label: label || undefined,
                                        },
                                    },
                                })
                            }}
                            onBlur={() =>
                                posthog.capture('sql breakdown label updated', { cleared: !customization?.label })
                            }
                        />
                    </div>
                }
            >
                <LemonButton
                    icon={<IconGear />}
                    noPadding
                    title="Breakdown settings"
                    onClick={() => {
                        setSettingsOpen(!settingsOpen)
                        if (!settingsOpen) {
                            posthog.capture('sql breakdown settings opened')
                        }
                    }}
                />
            </Popover>
        </div>
    )
}
