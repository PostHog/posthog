import { BIConfig } from '~/queries/schema/schema-business-intelligence'
import { ChartDisplayType } from '~/types'

export function isBIPivotTable(config: BIConfig): boolean {
    return (
        !config.querySnapshot &&
        (config.chartType === ChartDisplayType.TwoDimensionalHeatmap ||
            (config.chartType === ChartDisplayType.ActionsTable &&
                !config.compareFilter?.compare &&
                !config.source?.connectionId &&
                config.columns.some((field) => field.expression.trim() || field.name.trim())))
    )
}
