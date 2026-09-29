import { FileSystemImport } from '~/queries/schema/schema-general'

import { DecideRequestApiQuestions, DecideResponseApi } from 'products/ml_inference/frontend/generated/api.schemas'

import { sidebarProductMeta } from '../../sidebarProductMeta'
import { productsItemName } from './productsCatalog'

// Relative to the best app, which scores 1.
export const APP_MATCH_THRESHOLD = 0.25

const NO_APP = 'none'

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
export function buildAppRankingQuestions(items: FileSystemImport[]): DecideRequestApiQuestions {
    const keys = appKeys(items)
    const criteria: Record<string, string> = Object.fromEntries(
        items.map((item, index) => {
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
    result: DecideResponseApi,
    items: FileSystemImport[],
    query: string
): Record<string, number> {
    const answer = result.answers.app
    const probabilities = answer?.type === 'choice' ? (answer.probabilities ?? {}) : {}
    const keys = appKeys(items)
    const raw = items.map((_, index) => {
        const probability = probabilities[keys[index]]
        return typeof probability === 'number' && Number.isFinite(probability) ? Math.max(0, probability) : 0
    })
    const best = Math.max(0, ...raw)
    const relevant = best > 0 && best > (probabilities[NO_APP] ?? 0)
    // Partial words like "dash" carry too little intent for the model.
    const prefix = query.trim().toLowerCase()
    const scores: Record<string, number> = {}
    for (const [index, item] of items.entries()) {
        const named = prefix.length >= 3 && productsItemName(item).toLowerCase().startsWith(prefix)
        scores[item.path] = named ? 1 : relevant ? raw[index] / best : 0
    }
    return scores
}
