import { Column, SelectedYAxis } from '../dataVisualizationLogic'

export const getAvailableSeriesBreakdownColumns = (
    columns: Column[],
    selectedXAxis: string | null,
    selectedYAxis: (SelectedYAxis | null)[] | null
): Column[] => {
    const selectedYAxisNames = new Set((selectedYAxis ?? []).flatMap((series) => (series?.name ? [series.name] : [])))

    return columns.filter((column) => column.name !== selectedXAxis && !selectedYAxisNames.has(column.name))
}
