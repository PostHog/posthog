export interface FuseSearchMatch {
    // kea-typegen has a problem importing Fuse itself, so we have to duplicate this type
    indices: readonly [number, number][]
    key: string
}
