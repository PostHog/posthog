export interface VarValue {
    values: string[]
    texts?: string[]
    all: boolean
    allValue?: string
    multi?: boolean
    wildcard?: boolean
    none?: boolean
    adhoc?: boolean
}

export type ResolvedVars = Record<string, VarValue>
