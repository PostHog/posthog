import { GraphDataset } from '~/types'

/** Remove hidden items from nested datasets i.e. total value insights. */
export const filterNestedDataset = (
    hiddenLegendIndexes: number[] | undefined,
    datasets: GraphDataset[]
): GraphDataset[] => {
    if (!hiddenLegendIndexes) {
        return datasets
    }
    // If series are nested (for ActionsHorizontalBar and Pie), filter out the series by index
    const filterFn = (_: any, i: number): boolean => !hiddenLegendIndexes?.includes(i)
    return datasets.map((_data) => {
        // Performs a filter transformation on properties that contain arrayed data
        return Object.fromEntries(
            Object.entries(_data).map(([key, val]) =>
                Array.isArray(val) && val.length === datasets?.[0]?.actions?.length
                    ? [key, val?.filter(filterFn)]
                    : [key, val]
            )
        ) as GraphDataset
    })
}
