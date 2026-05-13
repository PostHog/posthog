/**
 * Hand-written API types — mirror products/agentic_tests/backend/presentation/serializers.py.
 * Regenerate via `hogli build:openapi` once the branch is merged.
 */

export type AgenticTestStatus = 'active' | 'paused' | 'proposed'

export type AgenticTestRunStatus = 'running' | 'passed' | 'failed' | 'timeout' | 'error'

export interface AgenticTestRun {
    id: string
    agentic_test: string
    started_at: string
    finished_at: string | null
    status: AgenticTestRunStatus
    duration_ms: number | null
    output: Record<string, unknown>
    error_message: string
    external_session_id: string
    screenshot_url: string
}

export interface AgenticTest {
    id: string
    name: string
    description: string
    target_url: string
    prompt: string
    status: AgenticTestStatus
    source_replay_id: string | null
    created_by: number | null
    created_at: string
    updated_at: string
    last_run_at: string | null
    last_run: AgenticTestRun | null
}

export interface AgenticTestDraft {
    name: string
    description: string
    target_url: string
    prompt: string
    status: AgenticTestStatus
    source_replay_id?: string | null
}
