let loading: Promise<void> | null = null

// The logged-out boot imports this through sceneLogic, so the taxonomy module loads lazily too.
export function loadCoreFilterDefinitions(): Promise<void> {
    loading ??= Promise.all([import('./taxonomy'), import('./core-filter-definitions-by-group.json')]).then(
        ([taxonomy, definitions]) => taxonomy.setCoreFilterDefinitions(definitions.default),
        (error) => {
            loading = null
            throw error
        }
    )
    return loading
}
