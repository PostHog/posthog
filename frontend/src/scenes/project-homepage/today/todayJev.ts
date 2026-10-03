import { ApiRequest } from 'lib/api'

import { HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { HogQLQueryString, hogql } from '~/queries/utils'

import {
    EXPANSION_QUESTION,
    READING_LABELS,
    READING_QUESTION,
    TodayKeyClause,
    TodayKeyClauseRequest,
    clauseRoleInput,
    expansionFor,
    expansionInput,
    marksWorthShowing,
    readingGuide,
    reportSentences,
    textClauses,
} from './todayKeyClauses'

const TAGS = { scene: 'TodayReport', name: 'today_report_cause' }

type ChoiceCell = [string, [string, number][], number] | null

function asPick(cell: ChoiceCell): { label: string; probability: number } | null {
    return cell && typeof cell[0] === 'string' && typeof cell[2] === 'number'
        ? { label: cell[0], probability: cell[2] }
        : null
}

async function runHogQL<T>(query: HogQLQueryString): Promise<T[]> {
    const response: HogQLQueryResponse<T[]> = await new ApiRequest().query().create({
        data: { query: { kind: NodeKind.HogQLQuery, query, tags: TAGS } },
    })
    return response.results
}

async function withExpansions(marks: TodayKeyClause[], sentences: string[]): Promise<TodayKeyClause[]> {
    if (!marks.length || !sentences.length) {
        return marks
    }
    const inputs = marks.flatMap((mark) => sentences.map((sentence) => expansionInput(mark, sentence)))
    const rows = await runHogQL<[string, number | null]>(
        hogql`SELECT item, jev(item, ${EXPANSION_QUESTION}, noul := ['true', 'false'], batch_size := 1) AS answer FROM (SELECT arrayJoin(${inputs}) AS item) LIMIT 400`
    )
    const byInput = new Map(rows.map(([input, probability]) => [input, probability]))
    return marks.map((mark) => ({
        ...mark,
        expansion: expansionFor(
            sentences,
            sentences.map((sentence) => byInput.get(expansionInput(mark, sentence)) ?? null)
        ),
    }))
}

/**
 * Asks Jev what each clause of each text tells the reader and keeps the surest clause for each role, then asks
 * which of the report's own sentences explain each kept clause, so its card can quote them.
 */
export async function fetchKeyClauses(
    requests: TodayKeyClauseRequest[],
    summary: string
): Promise<Record<string, TodayKeyClause[]>> {
    const prepared = requests.map((request) => ({ ...request, clauses: textClauses(request.text) }))
    const inputs = prepared.flatMap((request) => request.clauses.map((clause) => clauseRoleInput(request.text, clause)))
    if (!inputs.length) {
        return Object.fromEntries(requests.map((request) => [request.text, []]))
    }
    const rows = await runHogQL<[string, ChoiceCell]>(
        hogql`SELECT item, jev(item, ${READING_QUESTION}, choice := ${READING_LABELS}, batch_size := 1) AS answer FROM (SELECT arrayJoin(${inputs}) AS item) LIMIT 400`
    )
    const roleByInput = new Map(rows.map(([input, cell]) => [input, asPick(cell)]))
    const guides = prepared.map((request) =>
        readingGuide(
            request.clauses,
            request.roles,
            request.clauses.map((clause) => roleByInput.get(clauseRoleInput(request.text, clause)) ?? null)
        )
    )
    const sentences = reportSentences(
        summary,
        requests.map((request) => request.text)
    )
    const expanded = await withExpansions(guides.flat(), sentences)
    const shown = marksWorthShowing(expanded)
    let next = 0
    return Object.fromEntries(
        prepared.map((request, index) => [
            request.text,
            guides[index].map(() => expanded[next++]).filter((mark) => shown.has(mark)),
        ])
    )
}

const EXCERPT_QUESTION = 'Which numbered code excerpt shows the code that the finding describes?'
const EXCERPT_LABELS = ['1', '2', '3', '4', '5']
const MIN_EXCERPT_PROBABILITY = 0.5

/** Asks Jev which of several places in a file shows what a finding describes. */
export async function fetchExcerptChoice(finding: string, excerpts: string[]): Promise<number | null> {
    const input = `Finding:\n${finding}\n\n${excerpts.map((excerpt, index) => `Code excerpt ${index + 1}:\n${excerpt}`).join('\n\n')}`
    const [row] = await runHogQL<[string, ChoiceCell]>(
        hogql`SELECT item, jev(item, ${EXCERPT_QUESTION}, choice := ${EXCERPT_LABELS}, batch_size := 1) AS answer FROM (SELECT arrayJoin(${[input]}) AS item) LIMIT 1`
    )
    const pick = row ? asPick(row[1]) : null
    const index = pick ? Number(pick.label) - 1 : -1
    return pick && pick.probability >= MIN_EXCERPT_PROBABILITY && index >= 0 && index < excerpts.length ? index : null
}
