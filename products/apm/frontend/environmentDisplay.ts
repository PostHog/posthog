import type { LemonSelectOptionLeaf } from 'lib/lemon-ui/LemonSelect'

// The picker's state: null reads every environment, and an empty string reads spans that set no
// environment. The API lists the latter as null, so it can't collide with an environment named `default`.
export function environmentLabel(environment: string | null): string {
    if (environment === null) {
        return 'All environments'
    }
    return environment === '' ? '(no environment)' : environment
}

export function environmentOptions(
    environments: (string | null)[],
    selected: string | null
): LemonSelectOptionLeaf<string | null>[] {
    const values = environments.map((environment) => environment ?? '')
    if (selected !== null && !values.includes(selected)) {
        values.push(selected)
    }
    return [null, ...values].map((value) => ({ value, label: environmentLabel(value) }))
}
