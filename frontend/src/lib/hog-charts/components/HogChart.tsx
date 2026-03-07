import type { HogChartProps } from '../types'
import { Area } from './Area'
import { Bar } from './Bar'
import { BoxPlot } from './BoxPlot'
import { Funnel } from './Funnel'
import { Heatmap } from './Heatmap'
import { Lifecycle } from './Lifecycle'
import { Line } from './Line'
import { Number } from './Number'
import { Paths } from './Paths'
import { Pie } from './Pie'
import { Retention } from './Retention'
import { WorldMap } from './WorldMap'

/**
 * Universal chart component — renders any HogChart type via a discriminated
 * `type` prop.
 *
 * For maximum type safety, prefer importing the specific chart component
 * (e.g. `<Line />`, `<Bar />`). Use `<HogChart>` when the chart type is
 * determined at runtime.
 *
 * @example
 * ```tsx
 * <HogChart
 *     type="line"
 *     data={[{ label: 'Pageviews', data: [100, 200, 300] }]}
 *     labels={['Mon', 'Tue', 'Wed']}
 * />
 * ```
 */
export function HogChart(props: HogChartProps): JSX.Element {
    switch (props.type) {
        case 'line': {
            const { type: _, ...rest } = props
            return <Line {...rest} />
        }
        case 'bar': {
            const { type: _, ...rest } = props
            return <Bar {...rest} />
        }
        case 'area': {
            const { type: _, ...rest } = props
            return <Area {...rest} />
        }
        case 'pie': {
            const { type: _, ...rest } = props
            return <Pie {...rest} />
        }
        case 'number': {
            const { type: _, ...rest } = props
            return <Number {...rest} />
        }
        case 'funnel': {
            const { type: _, ...rest } = props
            return <Funnel {...rest} />
        }
        case 'retention': {
            const { type: _, ...rest } = props
            return <Retention {...rest} />
        }
        case 'paths': {
            const { type: _, ...rest } = props
            return <Paths {...rest} />
        }
        case 'worldmap': {
            const { type: _, ...rest } = props
            return <WorldMap {...rest} />
        }
        case 'boxplot': {
            const { type: _, ...rest } = props
            return <BoxPlot {...rest} />
        }
        case 'heatmap': {
            const { type: _, ...rest } = props
            return <Heatmap {...rest} />
        }
        case 'lifecycle': {
            const { type: _, ...rest } = props
            return <Lifecycle {...rest} />
        }
        case 'stickiness': {
            const { type: _, ...rest } = props
            return <Line {...rest} />
        }
        default:
            return <div>Unknown chart type</div>
    }
}
