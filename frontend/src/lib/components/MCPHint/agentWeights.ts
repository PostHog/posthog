import type { SurfaceKey } from './prompts'

export type AgentName = 'PostHog Code' | 'Claude' | 'Cursor' | 'Codex' | 'Gemini'

// Default flavor — biased toward PostHog Code so the rotator advertises our own agent first.
// Matches the previous behavior where "PostHog Code" appeared twice in the rotation array.
const DEFAULT_WEIGHTS: Record<AgentName, number> = {
    'PostHog Code': 2,
    Claude: 1,
    Cursor: 1,
    Codex: 1,
    Gemini: 1,
}

// Surfaces are weighted toward whichever agents users in that surface tend to live in.
// Devs writing SQL or wiring up flags live in IDE-flavored agents; PMs / leadership in chat agents.
const SURFACE_WEIGHT_OVERRIDES: Partial<Record<SurfaceKey, Partial<Record<AgentName, number>>>> = {
    'sql.execute': { 'PostHog Code': 3, Cursor: 3, Codex: 2, Claude: 1, Gemini: 0 },
    'actions.create': { 'PostHog Code': 3, Cursor: 2 },
    'error_tracking.assign': { 'PostHog Code': 3, Cursor: 2 },
    'feature_flags.create': { 'PostHog Code': 3, Cursor: 2 },
    'feature_flags.update': { 'PostHog Code': 3, Cursor: 2 },
    'workflows.create': { 'PostHog Code': 3, Cursor: 2 },
    'early_access_features.create': { 'PostHog Code': 3, Cursor: 1 },

    'dashboards.create': { 'PostHog Code': 3, Claude: 2, Gemini: 1 },
    'insights.create': { 'PostHog Code': 3, Claude: 2, Gemini: 1 },
    'experiments.create': { 'PostHog Code': 3, Claude: 2 },
    'experiments.launch': { 'PostHog Code': 3, Claude: 2 },
    'surveys.create': { 'PostHog Code': 3, Claude: 2 },
    'alerts.create': { 'PostHog Code': 3, Claude: 2 },
    'cohorts.create': { 'PostHog Code': 3, Claude: 1 },
    'annotations.create': { 'PostHog Code': 3, Claude: 1 },
}

export function getAgentRotation(surfaceKey?: SurfaceKey): AgentName[] {
    const weights: Record<AgentName, number> = surfaceKey
        ? { ...DEFAULT_WEIGHTS, ...(SURFACE_WEIGHT_OVERRIDES[surfaceKey] ?? {}) }
        : DEFAULT_WEIGHTS

    const rotation: AgentName[] = []
    for (const agent of Object.keys(weights) as AgentName[]) {
        const weight = weights[agent]
        for (let i = 0; i < weight; i++) {
            rotation.push(agent)
        }
    }
    return rotation.length > 0 ? rotation : ['PostHog Code']
}
