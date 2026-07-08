import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconGear, IconInfo, IconPlusSmall, IconTrash } from '@posthog/icons'
import {
    LemonButton,
    LemonColorButton,
    LemonColorGlyph,
    LemonColorPicker,
    LemonInput,
    LemonLabel,
    LemonSegmentedButton,
    LemonSelect,
    LemonSwitch,
    LemonTabs,
    LemonTag,
    Popover,
    Tooltip,
} from '@posthog/lemon-ui'

import { DataColorToken, getSeriesColor, getSeriesColorPalette } from 'lib/colors'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { dataThemeLogic } from 'scenes/dataThemeLogic'
import { INSIGHT_UNIT_OPTIONS_SHORT } from 'scenes/insights/aggregationAxisFormat'

import { ResultCustomizationBy } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { AxisSeries, dataVisualizationLogic } from '../dataVisualizationLogic'
import { HeatmapSeriesTab } from './Heatmap/HeatmapSeriesTab'
import { AxisBreakdownSeries, BREAKDOWN_LIMIT_LABEL, seriesBreakdownLogic } from './seriesBreakdownLogic'
import { getAvailableSeriesBreakdownColumns } from './seriesBreakdownUtils'
import { YSeriesLogicProps, YSeriesSettingsTab, ySeriesLogic } from './ySeriesLogic'

export const SeriesTab = (): JSX.Element => {
    const {
        columns,
        numericalColumns,
        xData,
        yData,
        responseLoading,
        showTableSettings,
        sourceTabularColumns,
        isTransposed,
        selectedXAxis,
        selectedYAxis,
        dataVisualizationProps,
        effectiveVisualizationType,
    } = useValues(dataVisualizationLogic)
    const { updateXSeries, addYSeries, updateSeriesIndex, deleteYSeries, setTransposeResults } =
        useActions(dataVisualizationLogic)
    const breakdownLogic = seriesBreakdownLogic({ key: dataVisualizationProps.key })
    const { selectedSeriesBreakdownColumn, showSeriesBreakdown } = useValues(breakdownLogic)
    const { addSeriesBreakdown } = useActions(breakdownLogic)

    const availableBreakdownColumns = getAvailableSeriesBreakdownColumns(columns, selectedXAxis, selectedYAxis)
    const hideAddYSeries = yData.length >= numericalColumns.length
    const hideAddSeriesBreakdown =
        showSeriesBreakdown || selectedXAxis === null || availableBreakdownColumns.length === 0
    const showSeriesBreakdownSelector =
        selectedXAxis !== null &&
        showSeriesBreakdown &&
        (selectedSeriesBreakdownColumn !== null || availableBreakdownColumns.length > 0)

    if (effectiveVisualizationType === ChartDisplayType.TwoDimensionalHeatmap) {
        return <HeatmapSeriesTab />
    }

    if (showTableSettings) {
        return (
            <div className="flex flex-col w-full p-3 gap-4">
                {effectiveVisualizationType === ChartDisplayType.ActionsTable && (
                    <LemonSwitch
                        className="flex-1 w-full"
                        label="Transpose results"
                        checked={isTransposed}
                        onChange={setTransposeResults}
                        tooltip="Rotate the table so rows become columns and columns become rows."
                    />
                )}
                <div>
                    <LemonLabel>Columns</LemonLabel>
                    {sourceTabularColumns.map((series, index) => (
                        <YSeries series={series} index={index} key={`${series.column.name}-${index}`} />
                    ))}
                </div>
            </div>
        )
    }

    const options = columns.map(({ name, type }) => ({
        value: name,
        label: (
            <div className="items-center flex-1">
                {name}
                <LemonTag className="ml-2" type="default">
                    {type.name}
                </LemonTag>
            </div>
        ),
    }))

    if (effectiveVisualizationType === ChartDisplayType.ActionsPie) {
        const valueColumn = selectedYAxis?.find((series) => series !== null)?.name ?? null
        const valueOptions = numericalColumns.map(({ name, type }) => ({
            value: name,
            label: (
                <div className="items-center flex-1">
                    {name}
                    <LemonTag className="ml-2" type="default">
                        {type.name}
                    </LemonTag>
                </div>
            ),
        }))

        // A pie encodes a single value column. Set it on the first series and drop any others
        // the chart may have carried over from another chart type.
        const setValueColumn = (columnName: string): void => {
            if (!selectedYAxis || selectedYAxis.length === 0) {
                addYSeries(columnName)
                return
            }
            updateSeriesIndex(0, columnName)
            for (let index = selectedYAxis.length - 1; index >= 1; index--) {
                deleteYSeries(index)
            }
        }

        return (
            <div className="flex flex-col w-full p-3">
                <LemonLabel className="mb-1">Label</LemonLabel>
                <LemonSelect
                    className="w-full"
                    value={xData !== null ? xData.column.name : 'None'}
                    options={options}
                    disabledReason={responseLoading ? 'Query loading...' : undefined}
                    onChange={(value) => {
                        const column = columns.find((n) => n.name === value)
                        if (column) {
                            updateXSeries(column.name)
                        }
                    }}
                />

                <LemonLabel className="mt-4 mb-1">Value</LemonLabel>
                <LemonSelect
                    className="w-full"
                    placeholder="Select a column"
                    value={valueColumn}
                    options={valueOptions}
                    disabledReason={responseLoading ? 'Query loading...' : undefined}
                    onChange={(value) => {
                        if (value) {
                            setValueColumn(value)
                        }
                    }}
                />
            </div>
        )
    }

    return (
        <div className="flex flex-col w-full p-3">
            <LemonLabel className="mb-1">X-axis</LemonLabel>
            <LemonSelect
                className="w-full"
                value={xData !== null ? xData.column.name : 'None'}
                options={options}
                disabledReason={responseLoading ? 'Query loading...' : undefined}
                onChange={(value) => {
                    const column = columns.find((n) => n.name === value)
                    if (column) {
                        updateXSeries(column.name)
                    }
                }}
            />
            {!hideAddSeriesBreakdown && (
                <LemonButton
                    className="mt-1"
                    type="tertiary"
                    onClick={() => addSeriesBreakdown(null)}
                    icon={<IconPlusSmall />}
                    fullWidth
                >
                    Add series breakdown
                </LemonButton>
            )}
            {showSeriesBreakdownSelector && <SeriesBreakdownSelector />}

            <LemonLabel className="mt-4 mb-1">Y-axis</LemonLabel>
            {yData.map((series, index) => (
                <YSeries series={series} index={index} key={`${series?.column.name}-${index}`} />
            ))}
            {!hideAddYSeries && (
                <LemonButton
                    className="mt-1"
                    type="tertiary"
                    onClick={() => addYSeries()}
                    icon={<IconPlusSmall />}
                    fullWidth
                >
                    Add Y-series
                </LemonButton>
            )}
        </div>
    )
}

const FORMATTING_STYLE_LABELS: Record<string, string> = {
    none: 'None',
    number: 'Number',
    short: 'Short Number',
    percent: 'Percentage',
    duration: 'Duration (s)',
    duration_ms: 'Duration (ms)',
}

const FORMATTING_STYLE_SHORT_LABELS: Record<string, string> = {
    none: '',
    number: '',
    short: INSIGHT_UNIT_OPTIONS_SHORT.short,
    percent: INSIGHT_UNIT_OPTIONS_SHORT.percentage,
    duration: INSIGHT_UNIT_OPTIONS_SHORT.duration,
    duration_ms: INSIGHT_UNIT_OPTIONS_SHORT.duration_ms,
}

const SeriesFormattingTag = ({ style }: { style?: string }): JSX.Element | null => {
    const shortLabel = style ? FORMATTING_STYLE_SHORT_LABELS[style] : ''

    if (!shortLabel) {
        return null
    }

    return (
        <LemonTag className="ml-2 shrink-0" type="default">
            {shortLabel}
        </LemonTag>
    )
}

const SeriesSelectLabel = ({
    name,
    color,
    showSeriesColor,
    formattingStyle,
    typeName,
    showType,
}: {
    name: string
    color: string
    showSeriesColor: boolean
    formattingStyle?: string
    typeName?: string
    showType?: boolean
}): JSX.Element => {
    return (
        <div className="flex items-center min-w-0 w-full">
            {showSeriesColor && <LemonColorGlyph className="mr-2 shrink-0" color={color} />}
            <span className="min-w-0 grow truncate">{name}</span>
            <SeriesFormattingTag style={formattingStyle} />
            {showType && typeName ? (
                <LemonTag className="ml-2 shrink-0" type="default">
                    {typeName}
                </LemonTag>
            ) : null}
        </div>
    )
}

const YSeries = ({ series, index }: { series: AxisSeries<number | null>; index: number }): JSX.Element => {
    const {
        columns,
        numericalColumns,
        responseLoading,
        dataVisualizationProps,
        showTableSettings,
        effectiveVisualizationType,
    } = useValues(dataVisualizationLogic)
    const { updateSeriesIndex, deleteYSeries } = useActions(dataVisualizationLogic)
    const { selectedSeriesBreakdownColumn } = useValues(seriesBreakdownLogic({ key: dataVisualizationProps.key }))

    const seriesLogicProps: YSeriesLogicProps = { series, seriesIndex: index, dataVisualizationProps }
    const seriesLogic = ySeriesLogic(seriesLogicProps)

    const { isSettingsOpen, canOpenSettings, activeSettingsTab } = useValues(seriesLogic)
    const { setSettingsOpen, submitFormatting, submitDisplay, setSettingsTab } = useActions(seriesLogic)

    const isPieChart = effectiveVisualizationType === ChartDisplayType.ActionsPie
    const seriesColor = series.settings?.display?.color ?? getSeriesColor(index)
    const showSeriesColor = !showTableSettings && !selectedSeriesBreakdownColumn

    const columnsInOptions = showTableSettings ? columns : numericalColumns
    const options = columnsInOptions.map(({ name, type }) => ({
        value: name,
        label: (
            <SeriesSelectLabel
                name={
                    series.settings?.display?.label && series.column.name === name
                        ? series.settings.display.label
                        : name
                }
                color={seriesColor}
                showSeriesColor={showSeriesColor}
                formattingStyle={series.settings?.formatting?.style}
            />
        ),
        labelInMenu: (
            <SeriesSelectLabel
                name={
                    series.settings?.display?.label && series.column.name === name
                        ? series.settings.display.label
                        : name
                }
                color={seriesColor}
                showSeriesColor={showSeriesColor}
                formattingStyle={series.settings?.formatting?.style}
                typeName={type.name}
                showType
            />
        ),
    }))

    const settingsTabs = isPieChart
        ? [
              {
                  label: Y_SERIES_SETTINGS_TABS[YSeriesSettingsTab.Formatting].label,
                  key: YSeriesSettingsTab.Formatting,
                  content: <YSeriesFormattingTab ySeriesLogicProps={seriesLogicProps} />,
              },
          ]
        : Object.values(Y_SERIES_SETTINGS_TABS).map(({ label, Component }, index) => ({
              label: label,
              key: Object.keys(Y_SERIES_SETTINGS_TABS)[index],
              content: <Component ySeriesLogicProps={seriesLogicProps} />,
          }))

    return (
        <div className="flex gap-1 mb-1">
            <LemonSelect
                className="grow flex-1 min-w-0"
                truncateText={{ maxWidthClass: 'max-w-full' }}
                value={series !== null ? series.column.name : 'None'}
                options={options}
                disabledReason={responseLoading ? 'Query loading...' : undefined}
                onChange={(value) => {
                    const column = columns.find((n) => n.name === value)
                    if (column) {
                        updateSeriesIndex(index, column.name)
                    }
                }}
            />
            <Popover
                overlay={
                    <div className="m-2">
                        <LemonTabs
                            activeKey={activeSettingsTab}
                            barClassName="justify-around"
                            onChange={(tab) => setSettingsTab(tab as YSeriesSettingsTab)}
                            tabs={settingsTabs}
                        />
                    </div>
                }
                visible={isSettingsOpen}
                placement="bottom"
                onClickOutside={() => {
                    submitFormatting()
                    submitDisplay()
                }}
            >
                <LemonButton
                    key="seriesSettings"
                    icon={<IconGear />}
                    noPadding
                    onClick={() => setSettingsOpen(true)}
                    disabledReason={!canOpenSettings && 'Select a column first'}
                />
            </Popover>
            {!showTableSettings && (
                <LemonButton
                    key="delete"
                    icon={<IconTrash />}
                    status="danger"
                    title="Delete Y-series"
                    noPadding
                    onClick={() => deleteYSeries(index)}
                />
            )}
        </div>
    )
}

export const YSeriesFormattingTab = ({ ySeriesLogicProps }: { ySeriesLogicProps: YSeriesLogicProps }): JSX.Element => {
    const { formatting } = useValues(ySeriesLogic(ySeriesLogicProps))
    const { updateSeriesIndex } = useActions(dataVisualizationLogic)

    const updateFormatting = (nextFormatting: typeof formatting): void => {
        updateSeriesIndex(ySeriesLogicProps.seriesIndex, ySeriesLogicProps.series.column.name, {
            formatting: {
                prefix: nextFormatting.prefix,
                suffix: nextFormatting.suffix,
                style: nextFormatting.style,
                decimalPlaces: Number.isNaN(nextFormatting.decimalPlaces) ? undefined : nextFormatting.decimalPlaces,
            },
        })
    }

    return (
        <Form logic={ySeriesLogic} props={ySeriesLogicProps} formKey="formatting" className="deprecated-space-y-4">
            {ySeriesLogicProps.series.column.type.isNumerical && (
                <LemonField name="style" label="Style" className="gap-1">
                    {({ value, onChange }) => (
                        <LemonSelect
                            value={value}
                            options={['none', 'number', 'short', 'percent', 'duration', 'duration_ms'].map(
                                (optionValue) => ({
                                    value: optionValue,
                                    label: FORMATTING_STYLE_LABELS[optionValue] ?? optionValue,
                                })
                            )}
                            onChange={(newValue) => {
                                onChange(newValue)
                                updateFormatting({
                                    ...formatting,
                                    style: newValue as typeof formatting.style,
                                })
                            }}
                        />
                    )}
                </LemonField>
            )}
            <LemonField name="prefix" label="Prefix">
                {({ value, onChange }) => (
                    <LemonInput
                        value={value ?? ''}
                        placeholder="$"
                        onChange={(newValue) => {
                            onChange(newValue)
                            updateFormatting({
                                ...formatting,
                                prefix: newValue,
                            })
                        }}
                    />
                )}
            </LemonField>
            <LemonField name="suffix" label="Suffix">
                {({ value, onChange }) => (
                    <LemonInput
                        value={value ?? ''}
                        placeholder="USD"
                        onChange={(newValue) => {
                            onChange(newValue)
                            updateFormatting({
                                ...formatting,
                                suffix: newValue,
                            })
                        }}
                    />
                )}
            </LemonField>
            {ySeriesLogicProps.series.column.type.isNumerical && (
                <LemonField name="decimalPlaces" label="Decimal places">
                    {({ value, onChange }) => (
                        <LemonInput
                            value={value ?? ''}
                            type="number"
                            min={0}
                            disabledReason={
                                formatting.style === 'short'
                                    ? 'Decimal places has no effect when using short number format'
                                    : undefined
                            }
                            onChange={(newValue) => {
                                onChange(newValue)
                                updateFormatting({
                                    ...formatting,
                                    decimalPlaces: newValue as typeof formatting.decimalPlaces,
                                })
                            }}
                        />
                    )}
                </LemonField>
            )}
        </Form>
    )
}

export const YSeriesDisplayTab = ({ ySeriesLogicProps }: { ySeriesLogicProps: YSeriesLogicProps }): JSX.Element => {
    const { showTableSettings, dataVisualizationProps, effectiveVisualizationType } = useValues(dataVisualizationLogic)
    const { selectedSeriesBreakdownColumn } = useValues(seriesBreakdownLogic({ key: dataVisualizationProps.key }))
    const { updateSeriesIndex } = useActions(dataVisualizationLogic)

    const isPieChart = effectiveVisualizationType === ChartDisplayType.ActionsPie
    const showColorPicker = !showTableSettings && !selectedSeriesBreakdownColumn
    const showLabelInput = showTableSettings || !selectedSeriesBreakdownColumn

    return (
        <Form logic={ySeriesLogic} props={ySeriesLogicProps} formKey="display" className="deprecated-space-y-4">
            {(showColorPicker || showLabelInput) && (
                <div className="flex gap-3">
                    {showColorPicker && (
                        <LemonField name="color" label="Color">
                            {({ value, onChange }) => (
                                <LemonColorPicker
                                    selectedColor={value}
                                    onSelectColor={(color) => {
                                        onChange(color)
                                        updateSeriesIndex(
                                            ySeriesLogicProps.seriesIndex,
                                            ySeriesLogicProps.series.column.name,
                                            {
                                                display: {
                                                    color: color,
                                                },
                                            }
                                        )
                                    }}
                                    colors={getSeriesColorPalette()}
                                    showCustomColor
                                    hideDropdown
                                    preventPopoverClose
                                    customColorValue={value}
                                />
                            )}
                        </LemonField>
                    )}
                    {showLabelInput && (
                        <LemonField name="label" label="Label">
                            {({ value, onChange }) => (
                                <LemonInput
                                    value={value}
                                    onChange={(label) => {
                                        onChange(label)
                                        updateSeriesIndex(
                                            ySeriesLogicProps.seriesIndex,
                                            ySeriesLogicProps.series.column.name,
                                            {
                                                display: {
                                                    label: label,
                                                },
                                            }
                                        )
                                    }}
                                />
                            )}
                        </LemonField>
                    )}
                </div>
            )}
            {!showTableSettings && !isPieChart && (
                <>
                    {!selectedSeriesBreakdownColumn && (
                        <LemonField name="trendLine" label="Trend line">
                            {({ value, onChange }) => (
                                <LemonSwitch
                                    checked={value}
                                    onChange={(newValue) => {
                                        onChange(newValue)
                                        updateSeriesIndex(
                                            ySeriesLogicProps.seriesIndex,
                                            ySeriesLogicProps.series.column.name,
                                            {
                                                display: {
                                                    trendLine: newValue,
                                                },
                                            }
                                        )
                                    }}
                                />
                            )}
                        </LemonField>
                    )}
                    <LemonField name="yAxisPosition" label="Y-axis position">
                        {({ value, onChange }) => (
                            <LemonSegmentedButton
                                value={value}
                                className="w-full"
                                options={[
                                    {
                                        label: 'Left',
                                        value: 'left',
                                    },
                                    {
                                        label: 'Right',
                                        value: 'right',
                                    },
                                ]}
                                onChange={(newValue) => {
                                    onChange(newValue)
                                    updateSeriesIndex(
                                        ySeriesLogicProps.seriesIndex,
                                        ySeriesLogicProps.series.column.name,
                                        {
                                            display: {
                                                yAxisPosition: newValue as 'left' | 'right',
                                            },
                                        }
                                    )
                                }}
                            />
                        )}
                    </LemonField>
                    <LemonField name="displayType" label="Display type">
                        {({ value, onChange }) => (
                            <LemonSegmentedButton
                                value={value}
                                className="w-full"
                                options={[
                                    {
                                        label: 'Auto',
                                        value: 'auto',
                                    },
                                    {
                                        label: 'Line',
                                        value: 'line',
                                    },
                                    {
                                        label: 'Bar',
                                        value: 'bar',
                                    },
                                    {
                                        label: 'Area',
                                        value: 'area',
                                    },
                                ]}
                                onChange={(newValue) => {
                                    onChange(newValue)
                                    updateSeriesIndex(
                                        ySeriesLogicProps.seriesIndex,
                                        ySeriesLogicProps.series.column.name,
                                        {
                                            display: {
                                                displayType: newValue as 'auto' | 'line' | 'bar' | 'area',
                                            },
                                        }
                                    )
                                }}
                            />
                        )}
                    </LemonField>
                </>
            )}
        </Form>
    )
}

const Y_SERIES_SETTINGS_TABS = {
    [YSeriesSettingsTab.Formatting]: {
        label: 'Formatting',
        Component: YSeriesFormattingTab,
    },
    [YSeriesSettingsTab.Display]: {
        label: 'Display',
        Component: YSeriesDisplayTab,
    },
}

export const SeriesBreakdownSelector = (): JSX.Element => {
    const { columns, responseLoading, selectedXAxis, selectedYAxis, dataVisualizationProps } =
        useValues(dataVisualizationLogic)
    const breakdownLogic = seriesBreakdownLogic({ key: dataVisualizationProps.key })
    const { selectedSeriesBreakdownColumn, seriesBreakdownData } = useValues(breakdownLogic)
    const { addSeriesBreakdown, deleteSeriesBreakdown } = useActions(breakdownLogic)

    const availableBreakdownColumns = getAvailableSeriesBreakdownColumns(columns, selectedXAxis, selectedYAxis)

    if (selectedXAxis === null || (selectedSeriesBreakdownColumn === null && availableBreakdownColumns.length === 0)) {
        return <></>
    }

    const seriesBreakdownOptions = availableBreakdownColumns.map(({ name, type }) => ({
        value: name,
        label: (
            <div className="items-center flex-1">
                {name}
                <LemonTag className="ml-2" type="default">
                    {type.name}
                </LemonTag>
            </div>
        ),
    }))

    return (
        <>
            <div className="flex gap-1 my-1">
                <LemonSelect
                    className="grow"
                    value={selectedSeriesBreakdownColumn !== null ? selectedSeriesBreakdownColumn : 'None'}
                    options={seriesBreakdownOptions}
                    disabledReason={responseLoading ? 'Query loading...' : undefined}
                    onChange={(value) => {
                        const column = columns.find((n) => n.name === value)
                        if (column) {
                            addSeriesBreakdown(column.name)
                        }
                    }}
                />
                <LemonButton
                    key="delete"
                    icon={<IconTrash />}
                    status="danger"
                    title="Delete series breakdown"
                    noPadding
                    onClick={() => deleteSeriesBreakdown()}
                />
            </div>
            <div className="ml-1 mt-2">
                {seriesBreakdownData.warning ? (
                    <div className="flex items-center gap-1.5 text-warning bg-warning-highlight rounded px-2 py-1 mt-1 mb-2 text-xs font-medium">
                        <span>{BREAKDOWN_LIMIT_LABEL}</span>
                        <Tooltip title={seriesBreakdownData.warning}>
                            <IconInfo className="text-base shrink-0 ml-auto" />
                        </Tooltip>
                    </div>
                ) : null}
                {seriesBreakdownData.seriesData.map((series, index) => (
                    <BreakdownSeries series={series} index={index} key={`${series.name}-${index}`} />
                ))}
            </div>
        </>
    )
}

const BreakdownSeries = ({
    series,
    index,
}: {
    series: AxisBreakdownSeries<number | null>
    index: number
}): JSX.Element => {
    const { chartSettings } = useValues(dataVisualizationLogic)
    const { updateChartSettings } = useActions(dataVisualizationLogic)
    const { getTheme } = useValues(dataThemeLogic)

    const theme = getTheme(undefined)
    const themeTokens = theme ? (Object.keys(theme) as DataColorToken[]) : []
    const selectedToken = chartSettings.resultCustomizations?.[series.breakdownValue]?.color ?? null
    const seriesColor = series.settings?.display?.color ?? getSeriesColor(index)

    return (
        <div className="flex gap-1 mb-2 items-center">
            <LemonColorPicker
                colorTokens={themeTokens}
                selectedColorToken={selectedToken}
                customButton={<LemonColorButton type="tertiary" color={seriesColor} className="mr-2" />}
                onSelectColorToken={(token) => {
                    updateChartSettings({
                        resultCustomizations: {
                            ...chartSettings.resultCustomizations,
                            [series.breakdownValue]: {
                                assignmentBy: ResultCustomizationBy.Value,
                                color: token,
                            },
                        },
                    })
                }}
                onClearColorToken={() => {
                    const { [series.breakdownValue]: _removed, ...rest } = chartSettings.resultCustomizations ?? {}
                    updateChartSettings({ resultCustomizations: rest })
                }}
            />
            <span>{series.name ? series.name : '[No value]'}</span>
        </div>
    )
}
