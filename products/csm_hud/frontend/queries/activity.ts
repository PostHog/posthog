import api from 'lib/api'

import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'

export interface NoteRow {
    id: string
    accountId: string
    subject: string | null
    note: string | null
    noteDate: string | null
    category: string | null
    author: string | null
}

export interface TaskRow {
    id: string
    accountId: string
    name: string | null
    dueDate: string | null
    completedAt: string | null
}

export interface TicketRow {
    zendeskOrgId: number
    subject: string
    status: string
    priority: string | null
    createdAt: string
}

export interface AccountActivity {
    notes: NoteRow[]
    tasks: TaskRow[]
    tickets: TicketRow[]
}

function sanitizeIdList(values: string[]): string {
    const safe = values.map((v) => v.replace(/[^A-Za-z0-9_-]/g, '')).filter((v) => v.length > 0)
    if (safe.length === 0) {
        return "''"
    }
    return safe.map((v) => `'${v}'`).join(', ')
}

function sanitizeIntList(values: number[]): string {
    const safe = values.filter((v) => Number.isInteger(v) && v > 0)
    if (safe.length === 0) {
        return '0'
    }
    return safe.join(', ')
}

const toStringOrNull = (v: unknown): string | null => {
    if (v == null) {
        return null
    }
    const s = String(v)
    return s.length === 0 ? null : s
}

async function runHogQL<T>(name: string, query: string, mapRow: (row: unknown[]) => T): Promise<T[]> {
    const node: HogQLQuery = {
        kind: NodeKind.HogQLQuery,
        query,
        tags: { productKey: 'csm_hud', scene: 'CSMHud', name: `csm_hud_${name}` },
    }
    const response = await api.query(node)
    return (response.results ?? []).map(mapRow)
}

export async function queryNotesBatch(accountIds: string[]): Promise<NoteRow[]> {
    if (accountIds.length === 0) {
        return []
    }
    const inList = sanitizeIdList(accountIds)
    const query = `
SELECT id, account_id, subject, note, note_date, category, author
FROM vitally_notes
WHERE account_id IN (${inList})
  AND archived_at IS NULL
ORDER BY account_id, note_date DESC
LIMIT 1000
`.trim()
    return runHogQL<NoteRow>('notes_batch', query, (row) => ({
        id: String(row[0] ?? ''),
        accountId: String(row[1] ?? ''),
        subject: toStringOrNull(row[2]),
        note: toStringOrNull(row[3]),
        noteDate: toStringOrNull(row[4]),
        category: toStringOrNull(row[5]),
        author: toStringOrNull(row[6]),
    }))
}

export async function queryTasksBatch(accountIds: string[]): Promise<TaskRow[]> {
    if (accountIds.length === 0) {
        return []
    }
    const inList = sanitizeIdList(accountIds)
    const query = `
SELECT id, account_id, name, due_date, completed_at
FROM vitally_tasks
WHERE account_id IN (${inList})
  AND archived_at IS NULL
ORDER BY account_id, due_date DESC
LIMIT 1000
`.trim()
    return runHogQL<TaskRow>('tasks_batch', query, (row) => ({
        id: String(row[0] ?? ''),
        accountId: String(row[1] ?? ''),
        name: toStringOrNull(row[2]),
        dueDate: toStringOrNull(row[3]),
        completedAt: toStringOrNull(row[4]),
    }))
}

export async function queryTicketsBatch(zendeskOrgIds: number[]): Promise<TicketRow[]> {
    if (zendeskOrgIds.length === 0) {
        return []
    }
    const inList = sanitizeIntList(zendeskOrgIds)
    const query = `
SELECT organization_id, subject, status, priority, toString(created_at) AS created_at
FROM zendesk_tickets
WHERE organization_id IN (${inList})
ORDER BY organization_id, created_at DESC
LIMIT 1000
`.trim()
    return runHogQL<TicketRow>('tickets_batch', query, (row) => ({
        zendeskOrgId: typeof row[0] === 'number' ? row[0] : parseInt(String(row[0] ?? '0'), 10) || 0,
        subject: String(row[1] ?? ''),
        status: String(row[2] ?? ''),
        priority: toStringOrNull(row[3]),
        createdAt: String(row[4] ?? ''),
    }))
}

export interface ActivityInputs {
    /** vitally account_ids === FleetRow.externalId */
    accountIds: string[]
    /** Map account_id → zendesk org id for the SAME account (from traits['zendesk.id']) */
    zendeskByAccount: Record<string, number>
}

/**
 * Load batched activity for the whole fleet and bucket per account. Returns
 * up to 5 most recent notes / tasks / tickets per account. Top-5 is applied
 * after the LIMIT 1000 batched read since the SQL `LIMIT` is global; rare
 * accounts with >5 notes are bounded by the global cap.
 */
export async function loadActivity({
    accountIds,
    zendeskByAccount,
}: ActivityInputs): Promise<Record<string, AccountActivity>> {
    const result: Record<string, AccountActivity> = {}
    if (accountIds.length === 0) {
        return result
    }
    for (const id of accountIds) {
        result[id] = { notes: [], tasks: [], tickets: [] }
    }

    // Sequential — same concurrency-guard reasoning as projection.
    const [notes, tasks, tickets] = [
        await queryNotesBatch(accountIds),
        await queryTasksBatch(accountIds),
        await queryTicketsBatch(Array.from(new Set(Object.values(zendeskByAccount).filter(Boolean)))),
    ]

    for (const note of notes) {
        const bucket = result[note.accountId]
        if (bucket && bucket.notes.length < 5) {
            bucket.notes.push(note)
        }
    }
    for (const task of tasks) {
        const bucket = result[task.accountId]
        if (bucket && bucket.tasks.length < 5) {
            bucket.tasks.push(task)
        }
    }
    // Fan tickets back out by account — multiple accounts can share a single
    // zendesk org id (rare but possible).
    const accountsByZendesk = new Map<number, string[]>()
    for (const [acc, z] of Object.entries(zendeskByAccount)) {
        if (!z) {
            continue
        }
        const arr = accountsByZendesk.get(z) ?? []
        arr.push(acc)
        accountsByZendesk.set(z, arr)
    }
    for (const ticket of tickets) {
        const accounts = accountsByZendesk.get(ticket.zendeskOrgId) ?? []
        for (const acc of accounts) {
            const bucket = result[acc]
            if (bucket && bucket.tickets.length < 5) {
                bucket.tickets.push(ticket)
            }
        }
    }

    return result
}
