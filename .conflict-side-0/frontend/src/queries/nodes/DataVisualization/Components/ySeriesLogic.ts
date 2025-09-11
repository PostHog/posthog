import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'

import { getSeriesColor } from 'lib/colors'

import {
    AxisSeries,
    DataVisualizationLogicProps,
    EmptyYAxisSeries,
    dataVisualizationLogic,
} from '../dataVisualizationLogic'
import type { ySeriesLogicType } from './ySeriesLogicType'

export interface YSeriesLogicProps {
    series: AxisSeries<number>
    seriesIndex: number
    dataVisualizationProps: DataVisualizationLogicProps
}

export enum YSeriesSettingsTab {
    Formatting = 'formatting',
    Display = 'display',
}

export const ySeriesLogic = kea<ySeriesLogicType>([
    path(['queries', 'nodes', 'DataVisualization', 'Components', 'ySeriesLogic']),
    key((props) => `${props.series?.column?.name ?? 'new'}-${props.seriesIndex ?? 0}`),
    connect((props: YSeriesLogicProps) => ({
        actions: [dataVisualizationLogic(props.dataVisualizationProps), ['updateSeriesIndex']],
    })),
    props({ series: EmptyYAxisSeries } as YSeriesLogicProps),
    actions({
        setSettingsOpen: (open: boolean) => ({ open }),
        setSettingsTab: (tab: YSeriesSettingsTab) => ({ tab }),
    }),
    reducers({
        isSettingsOpen: [
            false as boolean,
            {
                setSettingsOpen: (_, { open }) => open,
            },
        ],
        activeSettingsTab: [
            YSeriesSettingsTab.Formatting as YSeriesSettingsTab,
            {
                setSettingsTab: (_state, { tab }) => tab,
            },
        ],
    }),
    selectors({
        canOpenSettings: [
            (_s, p) => [p.series],
            (series) => {
                return series !== EmptyYAxisSeries
            },
        ],
    }),
    forms(({ actions, props }) => ({
        formatting: {
            defaults: {
                prefix: props.series?.settings?.formatting?.prefix ?? '',
                suffix: props.series?.settings?.formatting?.suffix ?? '',
                style: props.series?.settings?.formatting?.style ?? 'none',
                decimalPlaces: props.series?.settings?.formatting?.decimalPlaces,
            },
            submit: async (format) => {
                actions.updateSeriesIndex(props.seriesIndex, props.series.column.name, {
                    formatting: {
                        prefix: format.prefix,
                        suffix: format.suffix,
                        style: format.style,
                        decimalPlaces: Number.isNaN(format.decimalPlaces) ? undefined : format.decimalPlaces,
                    },
                })
                actions.setSettingsOpen(false)
            },
        },
        display: {
            defaults: {
                color: props.series?.settings?.display?.color ?? getSeriesColor(props.seriesIndex),
                label: props.series?.settings?.display?.label ?? '',
                trendLine: props.series?.settings?.display?.trendLine ?? false,
                yAxisPosition: props.series?.settings?.display?.yAxisPosition ?? 'left',
                displayType: props.series?.settings?.display?.displayType ?? 'auto',
            },
            submit: async (display) => {
                actions.updateSeriesIndex(props.seriesIndex, props.series.column.name, {
                    display: {
                        color: display.color,
                        label: display.label,
                        trendLine: display.trendLine,
                        yAxisPosition: display.yAxisPosition,
                        displayType: display.displayType,
                    },
                })
                actions.setSettingsOpen(false)
            },
        },
    })),
])
