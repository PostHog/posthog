import { z } from 'zod'

import { HogError } from '@/core/errors'
import { parseOrThrow, type ParseFailure, type Schema } from '@/core/schema'

import type { PostHogApi } from './api'

// A command that reads page after page stops here, so it never reads the whole of a large list.
export const MAX_PAGES = 20

export interface Page<T> {
    results: T[]
    count?: number
    next?: URL
}

// Lets a zod schema hold a hog Schema, so zod adds the place of a failing item, as in `results.3.name`.
function zodOf<T>(schema: Schema<T>): z.ZodType<T> {
    return z.unknown().transform((raw, ctx) => {
        const parsed = schema.safeParse(raw)
        if (parsed.success) {
            return parsed.data
        }
        for (const issue of parsed.error.issues) {
            ctx.addIssue({ code: 'custom', message: issue.message, path: [...issue.path] })
        }
        return z.NEVER
    })
}

export async function getPage<T>(api: PostHogApi, path: string, item: Schema<T>): Promise<Page<T>> {
    const page = z.object({ results: z.array(zodOf(item)), count: z.number().nullish(), next: z.string().nullish() })
    const { results, count, next } = await api.get(path, page)
    return {
        results,
        ...(typeof count === 'number' ? { count } : {}),
        ...(next ? { next: new URL(next) } : {}),
    }
}

// False when it stops at MAX_PAGES first. Keeping only a link's path and query sends every page to
// the configured host, whatever host the link names.
async function eachPage<T>(
    api: PostHogApi,
    path: string,
    item: Schema<T>,
    visit: (results: T[]) => boolean,
    maxPages = MAX_PAGES
): Promise<boolean> {
    let next: string | undefined = path
    for (let read = 0; next !== undefined; read++) {
        if (read === maxPages) {
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
// stopped at `maxPages` and a name missing from `found` can still be in the list.
export async function findNamed<T>(
    api: PostHogApi,
    path: string,
    item: Schema<T>,
    names: Iterable<string>,
    nameOf: (item: T) => string | null,
    maxPages = MAX_PAGES
): Promise<{ found: Map<string, T>; complete: boolean }> {
    const wanted = new Set(names)
    const found = new Map<string, T>()
    if (wanted.size === 0) {
        return { found, complete: true }
    }
    const complete = await eachPage(
        api,
        path,
        item,
        (page) => {
            for (const result of page) {
                const name = nameOf(result)
                if (name !== null && wanted.has(name)) {
                    found.set(name, result)
                }
            }
            return found.size === wanted.size
        },
        maxPages
    )
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
    const offset = Number(page.next?.searchParams.get('offset') ?? Number.NaN)
    return Number.isSafeInteger(offset) ? offset : null
}
