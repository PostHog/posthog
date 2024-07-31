import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'

import {
    AxisSeries,
    dataVisualizationLogic,
    DataVisualizationLogicProps,
    EmptyYAxisSeries,
} from '../dataVisualizationLogic'
import type { ySeriesLogicType } from './ySeriesLogicType'

export interface YSeriesLogicProps {
    series: AxisSeries<number>
    seriesIndex: number
    dataVisualizationProps: DataVisualizationLogicProps
}

export const ySeriesLogic = kea<ySeriesLogicType>([
    path(['queries', 'nodes', 'DataVisualization', 'Components', 'ySeriesLogic']),
    key((props) => props.series?.column?.name ?? `new-${props.seriesIndex}`),
    connect((props: YSeriesLogicProps) => ({
        actions: [dataVisualizationLogic(props.dataVisualizationProps), ['updateYSeries']],
    })),
    props({ series: EmptyYAxisSeries } as YSeriesLogicProps),
    actions({
        setSettingsOpen: (open: boolean) => ({ open }),
    }),
    reducers({
        isSettingsOpen: [
            false as boolean,
            {
                setSettingsOpen: (_, { open }) => open,
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
                decimalPlaces: props.series?.settings?.formatting?.decimalPlaces ?? '',
            },
            submit: async (format) => {
                actions.updateYSeries(props.seriesIndex, props.series.column.name, {
                    formatting: {
                        prefix: format.prefix,
                        suffix: format.suffix,
                        style: format.style,
                        decimalPlaces:
                            format.decimalPlaces === '' ? undefined : parseInt(format.decimalPlaces.toString(), 10),
                    },
                })
                actions.setSettingsOpen(false)
            },
        },
    })),
])
