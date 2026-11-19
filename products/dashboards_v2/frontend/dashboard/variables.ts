import type { DashboardV2SpecApi } from '../generated/api.schemas'

export type DashboardV2Variable = NonNullable<DashboardV2SpecApi['variables']>[number]

export type VariableValues = Record<string, string[]>

// pinned: the value a document and a shared link use for "every option"
export const ALL_VALUE = '$__all'

// pinned: URL search param prefix, the same one Grafana links use
const URL_PREFIX = 'var-'

export function variableOptions(variable: DashboardV2Variable): string[] | null {
    return variable.type === 'custom' || variable.type === 'interval' ? variable.options : null
}

function savedValue(variable: DashboardV2Variable): string[] {
    if (variable.current !== undefined && variable.current !== null) {
        return [variable.current].flat()
    }
    if (variable.type === 'constant') {
        return [variable.value]
    }
    if (variable.type === 'textbox') {
        return variable.default ? [variable.default] : []
    }
    const options = variableOptions(variable)
    if (!options?.length) {
        return []
    }
    return variable.includeAll ? [ALL_VALUE] : [options[0]]
}

export function resolveVariableValues(variables: DashboardV2Variable[], overrides: VariableValues): VariableValues {
    const values: VariableValues = {}
    for (const variable of variables) {
        const override = variable.type === 'constant' ? undefined : overrides[variable.name]
        values[variable.name] = override ?? savedValue(variable)
    }
    return values
}

export function variableOverridesFromSearch(searchParams: Record<string, unknown>): VariableValues {
    const overrides: VariableValues = {}
    for (const [key, value] of Object.entries(searchParams)) {
        if (key.startsWith(URL_PREFIX) && value !== undefined && value !== null) {
            overrides[key.slice(URL_PREFIX.length)] = [value].flat().map(String)
        }
    }
    return overrides
}

export function searchWithoutVariables(searchParams: Record<string, unknown>): Record<string, unknown> {
    return Object.fromEntries(Object.entries(searchParams).filter(([key]) => !key.startsWith(URL_PREFIX)))
}

export function variableOverridesToSearch(overrides: VariableValues): Record<string, string | string[]> {
    return Object.fromEntries(
        Object.entries(overrides).map(([name, values]) => [
            `${URL_PREFIX}${name}`,
            values.length === 1 ? values[0] : values,
        ])
    )
}
