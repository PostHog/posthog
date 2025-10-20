import { isObject } from 'lib/utils'

export interface ViewportResolution {
    width: string
    height: string
    href: string
}

export const getHrefFromSnapshot = (snapshot: unknown): string | undefined => {
    return isObject(snapshot) && 'data' in snapshot
        ? (snapshot.data as any)?.href || (snapshot.data as any)?.payload?.href
        : undefined
}
