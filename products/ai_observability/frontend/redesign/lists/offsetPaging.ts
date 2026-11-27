export interface OffsetPageParams {
    limit: number
    offset: number
}

export function pageParams(pageIndex: number, limit: number): OffsetPageParams {
    return { limit, offset: pageIndex * limit }
}

export function pageCount(count: number, limit: number): number {
    return Math.ceil(count / limit)
}
