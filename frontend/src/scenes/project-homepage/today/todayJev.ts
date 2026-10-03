import { ApiRequest } from 'lib/api'

import { HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { HogQLQueryString, hogql } from '~/queries/utils'

export interface JevPick {
    label: string
    probability: number
}

export interface JevClient {
    choice: (items: string[], question: string, labels: string[]) => Promise<(JevPick | null)[]>
    yes: (items: string[], question: string) => Promise<(number | null)[]>
}

type ChoiceCell = [string, [string, number][], number] | null

interface SavedAnswers {
    at: number
    answers: unknown[]
}

const TAGS = { scene: 'TodayReport', name: 'today_report_jev' }
const STORE_KEY = 'today-jev-answers'
const MAX_SAVED = 100

function hash(text: string): string {
    let value = 5381
    for (let index = 0; index < text.length; index++) {
        value = ((value << 5) + value + text.charCodeAt(index)) | 0
    }
    return (value >>> 0).toString(36)
}

function savedAnswers(): Record<string, SavedAnswers> {
    try {
        return JSON.parse(localStorage.getItem(STORE_KEY) ?? '{}')
    } catch {
        return {}
    }
}

function saveAnswers(key: string, answers: unknown[]): void {
    const newestFirst = Object.entries({ ...savedAnswers(), [key]: { at: Date.now(), answers } }).sort(
        (first, second) => second[1].at - first[1].at
    )
    try {
        localStorage.setItem(STORE_KEY, JSON.stringify(Object.fromEntries(newestFirst.slice(0, MAX_SAVED))))
    } catch {
        return
    }
}

const pending = new Map<string, Promise<unknown[]>>()

async function remembered<T>(parts: string[], ask: () => Promise<T[]>): Promise<T[]> {
    const key = hash(parts.join('\u0000'))
    const saved = savedAnswers()[key]
    if (saved) {
        return saved.answers as T[]
    }
    if (!pending.has(key)) {
        pending.set(
            key,
            ask()
                .then((answers) => {
                    saveAnswers(key, answers)
                    return answers
                })
                .finally(() => pending.delete(key))
        )
    }
    return (await pending.get(key)) as T[]
}

async function answersFor<T>(items: string[], query: HogQLQueryString): Promise<(T | null)[]> {
    const response: HogQLQueryResponse<[string, T][]> = await new ApiRequest().query().create({
        data: { query: { kind: NodeKind.HogQLQuery, query, tags: TAGS } },
    })
    const byItem = new Map(response.results)
    return items.map((item) => byItem.get(item) ?? null)
}

function asPick(cell: ChoiceCell): JevPick | null {
    return cell && typeof cell[0] === 'string' && typeof cell[2] === 'number'
        ? { label: cell[0], probability: cell[2] }
        : null
}

async function askChoice(items: string[], question: string, labels: string[]): Promise<(JevPick | null)[]> {
    const cells = await answersFor<ChoiceCell>(
        items,
        hogql`SELECT item, jev(item, ${question}, choice := ${labels}, batch_size := 1) AS answer FROM (SELECT arrayJoin(${items}) AS item) LIMIT ${items.length}`
    )
    return cells.map(asPick)
}

async function askYes(items: string[], question: string): Promise<(number | null)[]> {
    const answers = await answersFor<number>(
        items,
        hogql`SELECT item, jev(item, ${question}, noul := ['true', 'false'], batch_size := 1) AS answer FROM (SELECT arrayJoin(${items}) AS item) LIMIT ${items.length}`
    )
    return answers.map((answer) => (typeof answer === 'number' ? answer : null))
}

export const jev: JevClient = {
    choice: async (items, question, labels) =>
        items.length
            ? remembered(['choice', question, ...labels, ...items], () => askChoice(items, question, labels))
            : [],
    yes: async (items, question) =>
        items.length ? remembered(['yes', question, ...items], () => askYes(items, question)) : [],
}
