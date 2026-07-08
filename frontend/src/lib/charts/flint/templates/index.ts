import type { ChartTemplateDef } from 'flint-chart/core'

import { quillBarChartDef, quillGroupedBarChartDef, quillStackedBarChartDef } from './bar'
import { quillAreaChartDef, quillLineChartDef } from './line'
import { quillDoughnutChartDef, quillPieChartDef } from './pie'

/** Chart templates the quill backend implements. Names must match Flint's
 *  cross-backend registry names (`chart_spec.chartType`) exactly. */
export const quillTemplateDefs: ChartTemplateDef[] = [
    quillBarChartDef,
    quillGroupedBarChartDef,
    quillStackedBarChartDef,
    quillLineChartDef,
    quillAreaChartDef,
    quillPieChartDef,
    quillDoughnutChartDef,
]

export function quillGetTemplateDef(chartType: string): ChartTemplateDef | undefined {
    return quillTemplateDefs.find((t) => t.chart === chartType)
}
