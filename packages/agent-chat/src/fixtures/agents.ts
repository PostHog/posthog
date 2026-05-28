/**
 * Sample agent applications + revisions for stories and mocked console reads.
 *
 * Shapes mirror the Django `AgentApplicationSerializer` /
 * `AgentRevisionSerializer` field sets so v0.1 can swap fixtures for real API
 * responses without touching consumer code.
 */

export interface AgentApplicationFixture {
    id: string
    team: number
    name: string
    slug: string
    description: string
    live_revision: string | null
    archived: boolean
    archived_at: string | null
    created_by: { id: number; email: string; first_name: string }
    created_at: string
    updated_at: string
}

export type RevisionState = 'draft' | 'ready' | 'live' | 'archived'

export interface AgentRevisionFixture {
    id: string
    application: string
    parent_revision: string | null
    state: RevisionState
    bundle_uri: string
    bundle_sha256: string | null
    spec: Record<string, unknown>
    created_by: { id: number; email: string; first_name: string }
    created_at: string
    updated_at: string
}

const ben = { id: 1, email: 'ben@posthog.com', first_name: 'Ben' }
const ari = { id: 2, email: 'ari@posthog.com', first_name: 'Ari' }

export const weeklyDigest: AgentApplicationFixture = {
    id: '01998a01-1111-7000-8000-000000000001',
    team: 2,
    name: 'Weekly digest',
    slug: 'weekly-digest',
    description: 'Posts a Monday morning summary of the previous week to #product-eng.',
    live_revision: '01998a01-1111-7000-8000-000000000a01',
    archived: false,
    archived_at: null,
    created_by: ben,
    created_at: '2026-02-12T09:14:00Z',
    updated_at: '2026-05-20T16:42:00Z',
}

export const releaseConcierge: AgentApplicationFixture = {
    id: '01998a01-1111-7000-8000-000000000002',
    team: 2,
    name: 'Release concierge',
    slug: 'release-concierge',
    description: 'Drives the weekly release cut — drafts notes, opens PRs, pings owners on regressions.',
    live_revision: '01998a01-1111-7000-8000-000000000b01',
    archived: false,
    archived_at: null,
    created_by: ari,
    created_at: '2026-03-04T11:02:00Z',
    updated_at: '2026-05-27T22:08:00Z',
}

export const incidentTriager: AgentApplicationFixture = {
    id: '01998a01-1111-7000-8000-000000000003',
    team: 2,
    name: 'Incident triager',
    slug: 'incident-triager',
    description: 'On-call companion: enriches PagerDuty alerts with recent deploys and likely-blame commits.',
    live_revision: '01998a01-1111-7000-8000-000000000c01',
    archived: false,
    archived_at: null,
    created_by: ben,
    created_at: '2026-04-18T07:30:00Z',
    updated_at: '2026-05-28T13:15:00Z',
}

export const onboardingBuddy: AgentApplicationFixture = {
    id: '01998a01-1111-7000-8000-000000000004',
    team: 2,
    name: 'Onboarding buddy',
    slug: 'onboarding-buddy',
    description: "Walks new hires through the dev stack their first week. Read-only — answers questions.",
    live_revision: null,
    archived: false,
    archived_at: null,
    created_by: ari,
    created_at: '2026-05-22T15:00:00Z',
    updated_at: '2026-05-22T15:00:00Z',
}

export const archivedExperiment: AgentApplicationFixture = {
    id: '01998a01-1111-7000-8000-000000000005',
    team: 2,
    name: 'Old experiment (archived)',
    slug: 'old-experiment',
    description: 'Early test of the cron trigger. Superseded by the release concierge.',
    live_revision: null,
    archived: true,
    archived_at: '2026-04-01T10:00:00Z',
    created_by: ben,
    created_at: '2026-01-08T08:00:00Z',
    updated_at: '2026-04-01T10:00:00Z',
}

export const agents: AgentApplicationFixture[] = [weeklyDigest, releaseConcierge, incidentTriager, onboardingBuddy]

export const agentsWithArchived: AgentApplicationFixture[] = [...agents, archivedExperiment]

export const weeklyDigestLiveRevision: AgentRevisionFixture = {
    id: '01998a01-1111-7000-8000-000000000a01',
    application: weeklyDigest.id,
    parent_revision: null,
    state: 'live',
    bundle_uri: 'agent-bundles/weekly-digest/01998a01-1111-7000-8000-000000000a01',
    bundle_sha256: 'sha256:7f8c2a4b9e1d6c5f3a2b8e9d1c4f7a6b5e8d3c2a1b9f6e8d4c3a2b1e9f8d7c6a',
    spec: {
        model: 'anthropic/claude-sonnet-4-6',
        triggers: [{ type: 'cron', config: { schedule: '0 9 * * MON', timezone: 'US/Pacific' } }],
        tools: [
            { kind: 'native', id: '@posthog/query' },
            { kind: 'native', id: '@posthog/slack-post-message' },
        ],
        skills: [{ id: 'digest-shape', path: 'skills/digest-shape.md', description: 'How a good digest reads.' }],
        secrets: [],
        limits: { max_turns: 30, max_tool_calls: 100, max_wall_seconds: 300 },
    },
    created_by: ben,
    created_at: '2026-05-20T16:42:00Z',
    updated_at: '2026-05-20T16:42:00Z',
}

export const weeklyDigestDraftRevision: AgentRevisionFixture = {
    id: '01998a01-1111-7000-8000-000000000a02',
    application: weeklyDigest.id,
    parent_revision: weeklyDigestLiveRevision.id,
    state: 'draft',
    bundle_uri: 'agent-bundles/weekly-digest/01998a01-1111-7000-8000-000000000a02',
    bundle_sha256: null,
    spec: {
        model: 'anthropic/claude-sonnet-4-6',
        triggers: [{ type: 'cron', config: { schedule: '0 9 * * MON', timezone: 'US/Pacific' } }],
        tools: [
            { kind: 'native', id: '@posthog/query' },
            { kind: 'native', id: '@posthog/slack-post-message' },
            { kind: 'native', id: '@posthog/github-search' },
        ],
        skills: [
            { id: 'digest-shape', path: 'skills/digest-shape.md', description: 'How a good digest reads.' },
            { id: 'pr-callouts', path: 'skills/pr-callouts.md', description: 'How to summarize PRs.' },
        ],
        secrets: ['GITHUB_TOKEN'],
        limits: { max_turns: 30, max_tool_calls: 100, max_wall_seconds: 300 },
    },
    created_by: ben,
    created_at: '2026-05-28T11:00:00Z',
    updated_at: '2026-05-28T11:00:00Z',
}

export const weeklyDigestRevisions: AgentRevisionFixture[] = [weeklyDigestDraftRevision, weeklyDigestLiveRevision]
