import { actions, kea, listeners, path, reducers } from 'kea'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { OriginProduct } from 'products/posthog_ai/frontend/types/taskTypes'

import type { inboxTaskKickoffLogicType } from './inboxTaskKickoffLogicType'
import { SIGNAL_REPORT_TASK_IMPLEMENTATION_RELATIONSHIP, SignalReport, SignalReportTaskRelationship } from './types'

// Cloud-adapted port of desktop `useDiscussReport` / `useCreatePrReport`. These are
// task-kickoff actions (create a cloud Task linked to the report, then navigate to it) –
// NOT a live chat surface. The created task carries the SignalReport linkage so the
// backend's agent pipeline can pick it up.

// Report artefacts are paginated newest-first (default page size 100); `repo_selection` is
// written early in a research run, so a generous limit keeps it on the fetched page even for
// reports with many findings.
const REPO_SELECTION_ARTEFACT_FETCH_LIMIT = 1000

function buildCreatePrReportPrompt(report: SignalReport, feedback?: string): string {
    const base = `Act on PostHog Inbox report "${report.title ?? report.id}" (id ${report.id}). Investigate the root cause using the report's contributing findings, implement the fix, and open a PR.${
        report.summary ? `\n\nReport summary:\n${report.summary}` : ''
    }`
    const trimmed = feedback?.trim()
    if (!trimmed) {
        return base
    }
    return `${base}\n\nAdditional feedback from the user (take this into account):\n${trimmed}`
}

function buildDiscussReportPrompt(reportUrl: string, question: string): string {
    // The task is already linked to the report, but including the URL lets the agent open and read
    // the full report itself. The user's question follows after a blank line for clear separation.
    return `Let's discuss this PostHog Inbox report: ${reportUrl}\n\n${question.trim()}`
}

async function createReportTask(
    report: SignalReport,
    relationship: SignalReportTaskRelationship,
    prompt: string,
    fallbackTitle: string,
    requireRepository = false
): Promise<void> {
    // Use the repository the signals pipeline already selected for this report (its
    // `repo_selection` artefact), matching the desktop app and the auto-start flow. Never fall
    // back to an arbitrary project repo — `repositories[0]` previously leaked whichever repo
    // sorted first (e.g. a personal repo) and pinned the task to the wrong codebase.
    // Artefacts are paginated newest-first and `repo_selection` is written early in the run, so
    // fetch a high limit to keep it on the page even for reports with many findings.
    let repository: string | undefined
    try {
        const { results } = await api.signalReports.artefacts(report.id, { limit: REPO_SELECTION_ARTEFACT_FETCH_LIMIT })
        const selected = results.find((a) => a.type === 'repo_selection')?.content?.repository
        repository = typeof selected === 'string' && selected ? selected : undefined
    } catch (e) {
        // A genuine fetch failure must not masquerade as "no repository selected" — when a repo
        // is required, surface the real error so the user retries instead of waiting on analysis.
        if (requireRepository) {
            throw e
        }
        repository = undefined
    }

    // Opening a PR needs a concrete target repo. If selection hasn't resolved one (e.g. a
    // pending-input report), fail with a clear message instead of creating a task pinned to no
    // repository that can never open a PR. Discuss doesn't require a repo.
    if (requireRepository && !repository) {
        throw new Error('No repository has been selected for this report yet — try again once analysis finishes.')
    }

    const task = await api.tasks.create({
        title: report.title?.trim() || fallbackTitle,
        description: prompt,
        origin_product: OriginProduct.SIGNAL_REPORT,
        repository,
        // Linkage fields accepted by the tasks backend for the signal_report origin.
        signal_report: report.id,
        signal_report_task_relationship: relationship,
    } as Parameters<typeof api.tasks.create>[0])

    router.actions.push(urls.taskDetail(task.id))
}

export const inboxTaskKickoffLogic = kea<inboxTaskKickoffLogicType>([
    path(['scenes', 'inbox', 'inboxTaskKickoffLogic']),

    actions({
        discussReport: (report: SignalReport, reportUrl: string, question: string) => ({ report, reportUrl, question }),
        createPrFromReport: (report: SignalReport) => ({ report }),
        discussReportSuccess: true,
        discussReportFailure: true,
        createPrSuccess: true,
        createPrFailure: true,
    }),

    reducers({
        isDiscussing: [
            false,
            {
                discussReport: () => true,
                discussReportSuccess: () => false,
                discussReportFailure: () => false,
            },
        ],
        isCreatingPr: [
            false,
            {
                createPrFromReport: () => true,
                createPrSuccess: () => false,
                createPrFailure: () => false,
            },
        ],
    }),

    listeners(({ actions }) => ({
        discussReport: async ({ report, reportUrl, question }) => {
            try {
                await createReportTask(report, 'research', buildDiscussReportPrompt(reportUrl, question), 'Discuss report')
                actions.discussReportSuccess()
            } catch (error: any) {
                lemonToast.error(error?.detail || error?.message || 'Failed to start discussion')
                actions.discussReportFailure()
            }
        },
        createPrFromReport: async ({ report }) => {
            try {
                await createReportTask(
                    report,
                    SIGNAL_REPORT_TASK_IMPLEMENTATION_RELATIONSHIP,
                    buildCreatePrReportPrompt(report),
                    'Implement report fix',
                    true
                )
                actions.createPrSuccess()
            } catch (error: any) {
                lemonToast.error(error?.detail || error?.message || 'Failed to start PR task')
                actions.createPrFailure()
            }
        },
    })),
])
