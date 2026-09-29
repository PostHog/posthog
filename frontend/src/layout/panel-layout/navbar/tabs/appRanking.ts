import MiniSearch from 'minisearch'

import { FileSystemImport } from '~/queries/schema/schema-general'

import { DecideRequestApiQuestions, DecideResponseApi } from 'products/ml_inference/frontend/generated/api.schemas'

import { sidebarProductMeta } from '../../sidebarProductMeta'
import { productsItemName } from './productsCatalog'

// Relative to the best app, which scores 1.
export const APP_MATCH_THRESHOLD = 0.25
// With "none", 16 options: JevK5 reads them in one pass.
export const APP_CANDIDATES = 15

const NO_APP = 'none'
const STOP_WORDS = new Set(
    'a an the to of for and or in on at by with my our we i is are be do does how what why where which who when can could would should it its this that these those from as into about than then so if not no me you your their they them us'.split(
        ' '
    )
)

const searchIndexes = new WeakMap<FileSystemImport[], MiniSearch>()

/** The apps whose name, description, example, or keywords share words with the query, best first. */
export function searchApps(items: FileSystemImport[], query: string): FileSystemImport[] {
    let index = searchIndexes.get(items)
    if (!index) {
        index = new MiniSearch({
            fields: ['name', 'description', 'example', 'keywords'],
            processTerm: (term) => (STOP_WORDS.has(term.toLowerCase()) ? null : term.toLowerCase()),
            searchOptions: {
                boost: { name: 3, keywords: 1.5 },
                prefix: (term) => term.length >= 3,
                fuzzy: (term) => (term.length >= 5 ? 0.2 : false),
            },
        })
        index.addAll(
            items.map((item, id) => {
                const { description, example, keywords } = sidebarProductMeta(item)
                return { id, name: productsItemName(item), description, example, keywords: keywords?.join(' ; ') }
            })
        )
        searchIndexes.set(items, index)
    }
    return index.search(query).map((result) => items[result.id])
}

export interface AppMatchGroups {
    matching: FileSystemImport[]
    other: FileSystemImport[]
}

// The model reads each key next to its description.
function appKeys(items: FileSystemImport[]): string[] {
    const seen = new Set<string>([NO_APP])
    return items.map((item, index) => {
        const key = productsItemName(item)
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, '_')
            .replace(/^_|_$/g, '')
        const unique = !key || seen.has(key) ? `${key}_${index}` : key
        seen.add(unique)
        return unique
    })
}

// A yes/no question per app says yes to most apps; one choice makes them compete.
export function buildAppRankingQuestions(candidates: FileSystemImport[]): DecideRequestApiQuestions {
    const keys = appKeys(candidates)
    const criteria: Record<string, string> = Object.fromEntries(
        candidates.map((item, index) => {
            const { description, example } = sidebarProductMeta(item)
            const text = [description, example && `For example: ${example}`].filter(Boolean).join(' ')
            return [keys[index], (text || productsItemName(item)).slice(0, 500)]
        })
    )
    criteria[NO_APP] =
        'None of these apps: the request has nothing to do with a software product, its users, its data or its code.'
    return {
        app: {
            type: 'choice',
            instructions:
                'The user described something they want to do. Which PostHog app fits it best? The description may be a few words or unfinished; read it as intent.',
            criteria,
        },
    }
}

export function readAppRankings(
    result: DecideResponseApi | null,
    items: FileSystemImport[],
    candidates: FileSystemImport[],
    query: string
): Record<string, number> {
    const answer = result?.answers.app
    const probabilities = answer?.type === 'choice' ? (answer.probabilities ?? {}) : {}
    const keys = appKeys(candidates)
    const raw = candidates.map((_, index) => {
        const probability = probabilities[keys[index]]
        return typeof probability === 'number' && Number.isFinite(probability) ? Math.max(0, probability) : 0
    })
    const best = Math.max(0, ...raw)
    const relevant = best > 0 && best > (probabilities[NO_APP] ?? 0)
    const scores: Record<string, number> = Object.fromEntries(items.map((item) => [item.path, 0]))
    if (relevant) {
        candidates.forEach((item, index) => (scores[item.path] = raw[index] / best))
    }
    // Partial words like "dash" carry too little intent for the model.
    const prefix = query.trim().toLowerCase()
    for (const item of items) {
        if (prefix.length >= 3 && productsItemName(item).toLowerCase().startsWith(prefix)) {
            scores[item.path] = 1
        }
    }
    return scores
}
