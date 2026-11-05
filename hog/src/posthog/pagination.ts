import { z } from 'zod'

import { HogError } from '@/core/errors'
import { parseOrThrow, type ParseFailure, type Schema } from '@/core/schema'

import type { PostHogApi } from './api'

// A command that reads page after page stops here, so it never reads the whole of a large list.
export const MAX_PAGES = 20

export interface Page<T> {
    results: T[]
    // DRF's limit/offset and page-number paginators count the whole list. A cursor paginator doesn't.
    count?: number
    next?: URL
}

const PageBody = z.object({ results: z.array(z.unknown()), count: z.number().nullish(), next: z.string().nullish() })

// Checks each result against `item`, and names a failing one by its place, as in `results.3.name`.
function pageOf<T>(item: Schema<T>): Schema<Page<T>> {
    return {
        safeParse(raw) {
            const body = PageBody.safeParse(raw)
            if (!body.success) {
                return body
            }
            const results: T[] = []
            for (const [index, result] of body.data.results.entries()) {
                const parsed = item.safeParse(result)
                if (!parsed.success) {
                    const issues = parsed.error.issues.map((issue) => ({
                        ...issue,
                        path: ['results', index, ...issue.path],
                    }))
                    return { success: false, error: { issues } }
                }
                results.push(parsed.data)
            }
            const { count, next } = body.data
            return {
                success: true,
                data: {
                    results,
                    ...(typeof count === 'number' ? { count } : {}),
                    ...(next ? { next: new URL(next) } : {}),
                },
            }
        },
    }
}

export function getPage<T>(api: PostHogApi, path: string, item: Schema<T>): Promise<Page<T>> {
    return api.get(path, pageOf(item))
}

// False when it stops at MAX_PAGES before `visit` returns true or the list ends. A `next` link keeps
// only its path and query, so PostHogApi refuses one that points at another host.
async function eachPage<T>(
    api: PostHogApi,
    path: string,
    item: Schema<T>,
    visit: (results: T[]) => boolean
): Promise<boolean> {
    let next: string | undefined = path
    for (let read = 0; next !== undefined; read++) {
        if (read === MAX_PAGES) {
            return false
        }
        const page: Page<T> = await getPage(api, next, item)
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

export async function readAll<T>(api: PostHogApi, path: string, item: Schema<T>, tooLong: HogError): Promise<T[]> {
    const results: T[] = []
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
export async function findNamed<T>(
    api: PostHogApi,
    path: string,
    item: Schema<T>,
    names: Iterable<string>,
    nameOf: (item: T) => string | null
): Promise<{ found: Map<string, T>; complete: boolean }> {
    const wanted = new Set(names)
    const found = new Map<string, T>()
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
