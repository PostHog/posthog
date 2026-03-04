type ConfigDefs = Record<string, () => any>

type InferConfig<D extends ConfigDefs> = { [K in keyof D]: ReturnType<D[K]> }

export interface ConfigSection<D extends ConfigDefs> {
    defs: D
    defaults(): InferConfig<D>
}

export type ConfigOf<S extends { defs: ConfigDefs }> = InferConfig<S['defs']>

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
