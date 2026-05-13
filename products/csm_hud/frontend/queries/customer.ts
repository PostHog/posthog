import api from 'lib/api'

import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'

const UUID_RE = /^[0-9a-f-]+$/i

export interface TopUser {
    email: string
    userName: string
    role: string
    sessions: number
    lastSeen: string | null
}

export interface Ticket {
    subject: string
    status: string
    priority: string | null
    createdAt: string
}

export interface Note {
    id: string
    subject: string | null
    note: string | null
    noteDate: string | null
    category: string | null
    author: string | null
}

export interface Task {
    id: string
    name: string | null
    dueDate: string | null
    assignedTo: Record<string, unknown>
    description: string | null
    completedAt: string | null
}

async function runHogQL<T>(name: string, query: string, mapRow: (row: unknown[]) => T): Promise<T[]> {
    const node: HogQLQuery = {
        kind: NodeKind.HogQLQuery,
        query,
        tags: { productKey: 'csm_hud', scene: 'CSMHudCustomer', name: `csm_hud_${name}` },
    }
    const response = await api.query(node)
    return (response.results ?? []).map(mapRow)
}

function parseJson<T>(value: unknown, fallback: T): T {
    if (value == null) {
        return fallback
    }
    if (typeof value !== 'string') {
        return value as T
    }
    try {
        return JSON.parse(value) as T
    } catch {
        return fallback
    }
}

function toIntSafe(v: unknown): number {
    if (v == null || v === '') {
        return 0
    }
    const n = typeof v === 'number' ? v : parseInt(String(v), 10)
    return Number.isFinite(n) ? n : 0
}

const toStringOrNull = (v: unknown): string | null => {
    if (v == null) {
        return null
    }
    const s = String(v)
    return s.length === 0 ? null : s
}

export async function queryTopUsers(externalId: string): Promise<TopUser[]> {
    if (!externalId || !UUID_RE.test(externalId)) {
        return []
    }
    // The first-party events scan is scoped to team_id = 2 because PostHog
    // organization memberships only resolve to event distinct_ids in the prod
    // PostHog app project. Running this on any other team returns zero rows.
    const query = `
WITH members AS (
  SELECT DISTINCT user_id
  FROM postgres_posthog_organizationmembership
  WHERE organization_id = '${externalId}'
),
users AS (
  SELECT
    u.email,
    any(u.first_name) AS first_name,
    any(u.last_name) AS last_name,
    any(u.distinct_id) AS distinct_id
  FROM postgres_posthog_user u
  INNER JOIN members m ON m.user_id = u.id
  WHERE u.email IS NOT NULL AND u.email != ''
  GROUP BY u.email
),
sess AS (
  SELECT distinct_id, count(distinct $session_id) AS sessions, max(timestamp) AS last_seen
  FROM events
  WHERE team_id = 2
    AND distinct_id IN (SELECT distinct_id FROM users)
    AND timestamp >= now() - INTERVAL 30 DAY
  GROUP BY distinct_id
),
roles AS (
  SELECT email, any(JSONExtractString(coalesce(traits, '{}'), 'roleAtOrganization')) AS role
  FROM vitally_users
  WHERE accounts LIKE '%${externalId}%'
  GROUP BY email
)
SELECT
  u.email,
  trim(both ' ' from concat(coalesce(u.first_name, ''), ' ', coalesce(u.last_name, ''))) AS user_name,
  coalesce(r.role, '') AS role,
  coalesce(s.sessions, 0) AS sessions,
  toString(coalesce(s.last_seen, toDateTime(0))) AS last_seen
FROM users u
LEFT JOIN sess s ON s.distinct_id = u.distinct_id
LEFT JOIN roles r ON r.email = u.email
ORDER BY sessions DESC
LIMIT 5
`.trim()
    return runHogQL<TopUser>('customer_top_users', query, (row) => ({
        email: String(row[0] ?? ''),
        userName: String(row[1] ?? ''),
        role: String(row[2] ?? ''),
        sessions: toIntSafe(row[3]),
        lastSeen: toStringOrNull(row[4]),
    }))
}

export async function queryTickets(zendeskOrgId: number | null): Promise<Ticket[]> {
    if (!zendeskOrgId || zendeskOrgId <= 0 || !Number.isInteger(zendeskOrgId)) {
        return []
    }
    const query = `
SELECT
  t.subject AS subject,
  t.status AS status,
  t.priority AS priority,
  toString(t.created_at) AS created_at
FROM zendesk_tickets t
WHERE t.organization_id = ${zendeskOrgId}
ORDER BY t.created_at DESC
LIMIT 5
`.trim()
    return runHogQL<Ticket>('customer_tickets', query, (row) => ({
        subject: String(row[0] ?? ''),
        status: String(row[1] ?? ''),
        priority: toStringOrNull(row[2]),
        createdAt: String(row[3] ?? ''),
    }))
}

export async function queryNotes(accountId: string): Promise<Note[]> {
    if (!accountId || !UUID_RE.test(accountId)) {
        return []
    }
    const query = `
SELECT id, subject, note, note_date, category, author
FROM vitally_notes
WHERE account_id = '${accountId}'
  AND archived_at IS NULL
ORDER BY note_date DESC
LIMIT 5
`.trim()
    return runHogQL<Note>('customer_notes', query, (row) => ({
        id: String(row[0] ?? ''),
        subject: toStringOrNull(row[1]),
        note: toStringOrNull(row[2]),
        noteDate: toStringOrNull(row[3]),
        category: toStringOrNull(row[4]),
        author: toStringOrNull(row[5]),
    }))
}

export async function queryTasks(accountId: string): Promise<Task[]> {
    if (!accountId || !UUID_RE.test(accountId)) {
        return []
    }
    const query = `
SELECT id, name, due_date, assigned_to, description, completed_at
FROM vitally_tasks
WHERE account_id = '${accountId}'
  AND archived_at IS NULL
ORDER BY due_date DESC
LIMIT 5
`.trim()
    return runHogQL<Task>('customer_tasks', query, (row) => ({
        id: String(row[0] ?? ''),
        name: toStringOrNull(row[1]),
        dueDate: toStringOrNull(row[2]),
        assignedTo: parseJson<Record<string, unknown>>(row[3], {}),
        description: toStringOrNull(row[4]),
        completedAt: toStringOrNull(row[5]),
    }))
}
