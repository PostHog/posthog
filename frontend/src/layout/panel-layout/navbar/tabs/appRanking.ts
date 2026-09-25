import { FileSystemImport } from '~/queries/schema/schema-general'

import { DecideRequestApiQuestions, DecideResponseApi } from 'products/ml_inference/frontend/generated/api.schemas'

import { sidebarToolMeta } from '../../sidebarToolMeta'
import { appsItemName } from './appsCatalog'

export const APP_MATCH_THRESHOLD = 0.5

export interface AppMatchGroups {
    matching: FileSystemImport[]
    other: FileSystemImport[]
}

export function buildAppRankingQuestions(items: FileSystemImport[]): DecideRequestApiQuestions[] {
    const batches: DecideRequestApiQuestions[] = []
    for (let offset = 0; offset < items.length; offset += 32) {
        batches.push(
            Object.fromEntries(
                items.slice(offset, offset + 32).map((item, index) => [
                    `app_${offset + index}`,
                    {
                        type: 'noul',
                        instructions: `Would this PostHog app help with the user's goal? Interpret partial words and unfinished descriptions as intent. App: ${appsItemName(item)}. Category: ${item.category ?? ''}. ${sidebarToolMeta(item).description ?? ''} Example: ${sidebarToolMeta(item).example ?? ''}`,
                    },
                ])
            )
        )
    }
    return batches
}

export function readAppRankings(result: DecideResponseApi, items: FileSystemImport[]): Record<string, number> {
    const scores: Record<string, number> = {}
    for (const [index, item] of items.entries()) {
        const answer = result.answers[`app_${index}`]
        if (answer?.type === 'noul' && typeof answer.probability === 'number' && Number.isFinite(answer.probability)) {
            scores[item.path] = Math.max(0, Math.min(1, answer.probability))
        }
    }
    return scores
}
