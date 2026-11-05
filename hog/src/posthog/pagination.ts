import { z } from 'zod'

import { HogError } from '@/core/errors'
import { parseOrThrow, type ParseFailure } from '@/core/schema'

import type { PostHogApi } from './api'

// A command that reads page after page stops here, so it never reads the whole of a large list.
export const MAX_PAGES = 20

export interface Page<T> {
    results: T[]
    // DRF's limit/offset and page-number paginators count the whole list. A cursor paginator doesn't.
    count?: number
    next?: URL
}

export async function getPage<S extends z.ZodType>(api: PostHogApi, path: string, item: S): Promise<Page<z.output<S>>> {
    const body = await api.get(
        path,
        z.object({ results: z.array(item), count: z.number().nullish(), next: z.string().nullish() })
    )
    return {
        results: body.results,
        ...(typeof body.count === 'number' ? { count: body.count } : {}),
        ...(body.next ? { next: new URL(body.next) } : {}),
    }
}

// False when it stops at MAX_PAGES before `visit` returns true or the list ends. A `next` link keeps
// only its path and query, so PostHogApi refuses one that points at another host.
async function eachPage<S extends z.ZodType>(
    api: PostHogApi,
    path: string,
    item: S,
    visit: (results: z.output<S>[]) => boolean
): Promise<boolean> {
    let next: string | undefined = path
    for (let read = 0; next !== undefined; read++) {
        if (read === MAX_PAGES) {
            return false
        }
        const page: Page<z.output<S>> = await getPage(api, next, item)
        if (visit(page.results)) {
            return true
        }
        next = page.next ? page.next.pathname + page.next.search : undefined
    }
    return true
}

export function listTooLong(noun: string, hint: string): HogError {
    return new HogError('list_too_long', `The project has more ${noun} than hog reads in one command.`, hint)
}

export async function readAll<S extends z.ZodType>(
    api: PostHogApi,
    path: string,
    item: S,
    tooLong: HogError
): Promise<z.output<S>[]> {
    const results: z.output<S>[] = []
    const complete = await eachPage(api, path, item, (page) => {
        results.push(...page)
        return false
    })
    if (!complete) {
        throw tooLong
    }
    return results
}

// Reads pages until every name has turned up or the list ends. When `complete` is false, hog
// stopped at MAX_PAGES and a name missing from `found` can still be in the list.
export async function findNamed<S extends z.ZodType>(
    api: PostHogApi,
    path: string,
    item: S,
    names: Iterable<string>,
    nameOf: (item: z.output<S>) => string | null
): Promise<{ found: Map<string, z.output<S>>; complete: boolean }> {
    const wanted = new Set(names)
    const found = new Map<string, z.output<S>>()
    if (wanted.size === 0) {
        return { found, complete: true }
    }
    const complete = await eachPage(api, path, item, (page) => {
        for (const result of page) {
            const name = nameOf(result)
            if (name !== null && wanted.has(name)) {
                found.set(name, result)
            }
        }
        return found.size === wanted.size
    })
    return { found, complete }
}

function wholeNumber(min: number, max?: number): z.ZodType<number, string> {
    const error = `It must be a whole number ${max === undefined ? `of ${min} or more` : `from ${min} to ${max}`}.`
    const number = z.int({ error }).min(min, { error })
    return z
        .string()
        .regex(/^\d+$/, { error })
        .transform(Number)
        .pipe(max === undefined ? number : number.max(max, { error }))
}

// PostHog answers at most 1000 rows a page from a limit/offset list (BoundedLimitOffsetPagination).
export const MAX_LIMIT = 1000
const LimitSchema = wholeNumber(1, MAX_LIMIT)
const OffsetSchema = wholeNumber(0)

export const parseLimit = (raw: string, failure: ParseFailure): number => parseOrThrow(LimitSchema, raw, failure)
export const parseOffset = (raw: string, failure: ParseFailure): number => parseOrThrow(OffsetSchema, raw, failure)

export function nextOffset(page: Page<unknown>): number | null {
    const offset = page.next?.searchParams.get('offset')
    return offset ? Number(offset) : null
}
