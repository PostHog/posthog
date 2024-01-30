import { MobileStyles } from '../mobile.types'

export interface ConversionResult<T> {
    result: T
    context: ConversionContext
}

export interface ConversionContext {
    timestamp: number
    idSequence: Generator<number>
    // in some contexts we want to be able to skip nodes that have already been processed
    // for example updates are processed as a remove and then an add of the whole tree
    // this means the mobile app doesn't have to store and diff the tree
    // it can just send the whole thing over
    // but multiple nearby updates can result in the same node being present
    // in the tree multiple times
    // we track which nodes have been processed to avoid adding them multiple times
    skippableNodes?: Set<number>
    styleOverride?: StyleOverride
}

// StyleOverride is defined here and not in the schema
// because these are overrides that the transformer is allowed to make
// not that clients are allowed to request
export type StyleOverride = MobileStyles & { bottom?: true; 'z-index'?: number }
