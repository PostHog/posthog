import { HogFunctionType, HogFunctionTypeType } from '~/types'

export type IsDataPipelinesListEmptyProps = {
    kind: HogFunctionTypeType
    hogFunctions: HogFunctionType[]
    hogFunctionsLoading: boolean
    hogFunctionPluginsDestinations: HogFunctionType[] | null
    hogFunctionBatchExports: HogFunctionType[] | null
    hogFunctionPluginsSiteApps: HogFunctionType[] | null
}

/**
 * The destinations list is assembled from three independent sources: hog functions, batch exports,
 * and legacy plugin destinations. A source that has not resolved yet is `null`, which is unknown
 * rather than empty, so the list only counts as empty once every source for the kind has answered.
 */
export function isDataPipelinesListEmpty({
    kind,
    hogFunctions,
    hogFunctionsLoading,
    hogFunctionPluginsDestinations,
    hogFunctionBatchExports,
    hogFunctionPluginsSiteApps,
}: IsDataPipelinesListEmptyProps): boolean {
    if (hogFunctionsLoading || hogFunctions.length > 0) {
        return false
    }

    const manualSources: (HogFunctionType[] | null)[] =
        kind === 'destination'
            ? [hogFunctionPluginsDestinations, hogFunctionBatchExports]
            : kind === 'site_app'
              ? [hogFunctionPluginsSiteApps]
              : []

    return manualSources.every((source) => source !== null && source.length === 0)
}
