import { HogFunctionType } from '~/types'

export type IsDataPipelinesListEmptyProps = {
    hogFunctions: HogFunctionType[]
    hogFunctionsLoading: boolean
    /** The non-hog-function sources for this kind, each null until it loads. */
    manualSources: (HogFunctionType[] | null)[]
}

/**
 * A destination can be a hog function, a batch export, or a legacy plugin, and each kind loads
 * separately. A source that has not resolved yet is `null`, which is unknown rather than empty,
 * so the list only counts as empty once every source has answered.
 */
export function isDataPipelinesListEmpty({
    hogFunctions,
    hogFunctionsLoading,
    manualSources,
}: IsDataPipelinesListEmptyProps): boolean {
    if (hogFunctionsLoading || hogFunctions.length > 0) {
        return false
    }

    return manualSources.every((source) => source !== null && source.length === 0)
}
