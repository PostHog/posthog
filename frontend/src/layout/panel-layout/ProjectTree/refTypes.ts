/**
 * Whether a file system row is of `type`. A trailing slash makes `type` a prefix covering several
 * internal types, e.g. "hog/" matches "hog/site_destination" (see `ProjectTreeRef`).
 */
export function matchesRefType(rowType: string | undefined, type: string): boolean {
    return type.endsWith('/') ? !!rowType?.startsWith(type) : rowType === type
}

export function refTypeParams(type: string): { type?: string; type__startswith?: string } {
    return type.endsWith('/') ? { type__startswith: type } : { type }
}
