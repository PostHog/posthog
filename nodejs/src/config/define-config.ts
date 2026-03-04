type ConfigDefs = Record<string, () => any>

type InferConfig<D extends ConfigDefs> = { [K in keyof D]: ReturnType<D[K]> }

export interface ConfigSection<D extends ConfigDefs> {
    defs: D
    defaults(): InferConfig<D>
}

export type ConfigOf<S extends { defs: ConfigDefs }> = InferConfig<S['defs']>

/**
 * Define a config section. Each key is a factory function that returns the default value.
 * Type is inferred from the factory return type.
 */
export function defineConfig<D extends ConfigDefs>(defs: D): ConfigSection<D> {
    return {
        defs,
        defaults(): InferConfig<D> {
            const result: any = {}
            for (const [key, fn] of Object.entries(defs)) {
                result[key] = fn()
            }
            return result
        },
    }
}

/**
 * Merge multiple config sections into a single defaults object.
 * Throws if any keys are duplicated across sections.
 */
export function mergeConfigs(...sections: ConfigSection<any>[]): Record<string, unknown> {
    const seen = new Map<string, number>()
    for (let i = 0; i < sections.length; i++) {
        for (const key of Object.keys(sections[i].defs)) {
            if (seen.has(key)) {
                throw new Error(
                    `Config key "${key}" is defined in multiple config sections (indices ${seen.get(key)} and ${i})`
                )
            }
            seen.set(key, i)
        }
    }

    const result: Record<string, unknown> = {}
    for (const section of sections) {
        Object.assign(result, section.defaults())
    }
    return result
}
