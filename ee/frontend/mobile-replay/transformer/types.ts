import { MobileStyles } from '../mobile.types'

export interface ConversionResult<T> {
    result: T
    context: ConversionContext
}

export interface ConversionContext {
    timestamp: number
    idSequence: Generator<number>
    styleOverride?: StyleOverride
}

// StyleOverride is defined here and not in the schema
// because these are overrides that the transformer is allowed to make
// not that clients are allowed to request
export type StyleOverride = MobileStyles & { bottom?: true; backgroundRepeat?: 'no-repeat' | 'unset' }
