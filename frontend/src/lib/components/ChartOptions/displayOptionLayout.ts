import { ReactNode } from 'react'

export type DisplayOptionTabKey = 'general' | 'axes' | 'lines'

interface DisplayOptionSectionLayout {
    key: string
    title?: string
    tooltip?: string
    dataAttr?: string
    options: readonly string[]
}

interface DisplayOptionTabLayout {
    key: DisplayOptionTabKey
    label: string
    sections: readonly DisplayOptionSectionLayout[]
}

// Every chart display option, in the order the insight Options panel and the SQL editor's Display tab show
// them. Each surface says which of these options it supports for the current chart.
export const DISPLAY_OPTION_LAYOUT = [
    {
        key: 'general',
        label: 'General',
        sections: [
            {
                key: 'display',
                dataAttr: 'options-display-section',
                options: [
                    'metric',
                    'lifecycleStacking',
                    'valuesOnSeries',
                    'valueLabelPosition',
                    'valueLabelBackground',
                    'valueLabelFontSize',
                    'valueLabelRotation',
                    'lifecyclePercentages',
                    'percentStack',
                    'stackBreakdown',
                    'sliceNames',
                    'pieSliceContent',
                    'pieValueDisplay',
                    'pieTotal',
                    'showTotalRow',
                    'showNullsAsZero',
                    'barSpacing',
                    'hideIncompleteFunnelPeriods',
                    'alertAnomalyPoints',
                    'legend',
                    'excludeOutliers',
                ],
            },
            {
                key: 'annotations',
                title: 'Annotations',
                tooltip:
                    'Annotations are saved on an insight, a dashboard, the project, or the organization. Choose which of those to show here.',
                options: ['annotations'],
            },
            { key: 'unit', title: 'Unit', options: ['unit'] },
            {
                key: 'color-customization',
                title: 'Color customization by',
                tooltip:
                    "You can customize the appearance of individual results in your insights. This can be done based on the result's name (e.g., customize the breakdown value 'pizza' for the first series) or based on the result's rank (e.g., customize the first dataset in the results).",
                options: ['resultCustomizationBy'],
            },
            { key: 'decimal-places', options: ['decimalPlaces'] },
            { key: 'retention-dashboards', title: 'On dashboards', options: ['retentionDashboardDisplay'] },
            {
                key: 'retention-cohort-labels',
                title: 'Cohort labels start at',
                tooltip:
                    'Controls the starting index used to label cohort columns. Display only, does not affect the calculations.',
                options: ['retentionCohortLabelStart'],
            },
        ],
    },
    {
        key: 'axes',
        label: 'Axes',
        sections: [
            {
                key: 'x-axis',
                title: 'X-axis',
                options: [
                    'xAxisLabel',
                    'xAxisScale',
                    'xAxisBeginAtZero',
                    'xAxisDateFormat',
                    'xAxisTickRotation',
                    'xAxisShowTicks',
                    'xAxisBorder',
                ],
            },
            {
                key: 'y-axis',
                title: 'Y-axis',
                options: [
                    'yAxisLabel',
                    'yAxisRange',
                    'yAxisBeginAtZero',
                    'multipleYAxes',
                    'yAxisShowTicks',
                    'yAxisGridLines',
                    'yAxisBorder',
                    'yAxisScale',
                ],
            },
            {
                key: 'right-y-axis',
                title: 'Right Y-axis',
                options: [
                    'rightYAxisLabel',
                    'rightYAxisBeginAtZero',
                    'rightYAxisShowTicks',
                    'rightYAxisGridLines',
                    'rightYAxisScale',
                ],
            },
        ],
    },
    {
        key: 'lines',
        label: 'Lines',
        sections: [
            { key: 'style', title: 'Style', options: ['lineStyle', 'smoothing'] },
            {
                key: 'retention-series-colors',
                title: 'Cohort line colors',
                tooltip: 'One shade draws every cohort in the same color, with the newest cohort the most solid.',
                options: ['retentionSeriesColorMode'],
            },
            {
                key: 'overlays',
                title: 'Overlays',
                dataAttr: 'options-overlays-section',
                options: [
                    'trendLines',
                    'movingAverage',
                    'movingAverageIntervals',
                    'confidenceInterval',
                    'confidenceLevel',
                    'alertThresholdLines',
                    'retentionMeanLine',
                ],
            },
        ],
    },
] as const satisfies readonly DisplayOptionTabLayout[]

type Layout = typeof DISPLAY_OPTION_LAYOUT
export type DisplayOptionSectionKey = Layout[number]['sections'][number]['key']
export type DisplayOptionKey = Layout[number]['sections'][number]['options'][number]

export interface DisplayOptionItemInput {
    element: ReactNode
    // Options set away from their default, summed into the badge on the Options button.
    changedCount?: number
}

// An option a surface doesn't offer for the current chart is left out, or set to `false`.
export type DisplayOptionItems = Partial<Record<DisplayOptionKey, DisplayOptionItemInput | false | null | undefined>>

export interface DisplayOptionItem {
    key: DisplayOptionKey
    element: ReactNode
}

export interface DisplayOptionSection {
    key: DisplayOptionSectionKey
    title?: string
    tooltip?: string
    dataAttr?: string
    items: DisplayOptionItem[]
}

export interface DisplayOptionTab {
    key: DisplayOptionTabKey
    label: string
    sections: DisplayOptionSection[]
    count: number
}

export interface DisplayOptionSectionOverride {
    title?: string
    // `null` drops the layout's tooltip on a surface where it doesn't apply.
    tooltip?: string | null
}

export interface GroupDisplayOptionsOptions {
    singleTab?: boolean
    sections?: Partial<Record<DisplayOptionSectionKey, DisplayOptionSectionOverride>>
}

export function countTruthy(...flags: unknown[]): number {
    return flags.filter(Boolean).length
}

export function groupDisplayOptions(
    items: DisplayOptionItems,
    { singleTab = false, sections: overrides = {} }: GroupDisplayOptionsOptions = {}
): { tabs: DisplayOptionTab[]; count: number } {
    const layout: readonly DisplayOptionTabLayout[] = DISPLAY_OPTION_LAYOUT

    const allTabs: DisplayOptionTab[] = layout.map((tab) => {
        let count = 0
        const sections = tab.sections.flatMap((section): DisplayOptionSection[] => {
            const sectionItems = (section.options as readonly DisplayOptionKey[]).flatMap((key) => {
                const item = items[key]
                if (!item) {
                    return []
                }
                count += item.changedCount ?? 0
                return [{ key, element: item.element }]
            })
            if (sectionItems.length === 0) {
                return []
            }
            const override = overrides[section.key as DisplayOptionSectionKey]
            const tooltip = override?.tooltip === null ? undefined : (override?.tooltip ?? section.tooltip)
            return [
                {
                    key: section.key as DisplayOptionSectionKey,
                    title: override?.title ?? section.title,
                    tooltip,
                    dataAttr: section.dataAttr,
                    items: sectionItems,
                },
            ]
        })
        return { key: tab.key, label: tab.label, sections, count }
    })

    const tabs = (
        singleTab
            ? [
                  {
                      key: 'general' as const,
                      label: 'General',
                      sections: allTabs.flatMap((tab) => tab.sections),
                      count: allTabs.reduce((sum, tab) => sum + tab.count, 0),
                  },
              ]
            : allTabs
    ).filter((tab) => tab.sections.length > 0)

    return { tabs, count: tabs.reduce((sum, tab) => sum + tab.count, 0) }
}
