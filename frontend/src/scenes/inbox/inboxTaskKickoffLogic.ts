import { actions, kea, listeners, path, reducers } from 'kea'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { OriginProduct } from 'products/tasks/frontend/types'

import type { inboxTaskKickoffLogicType } from './inboxTaskKickoffLogicType'
import { SIGNAL_REPORT_TASK_IMPLEMENTATION_RELATIONSHIP, SignalReport, SignalReportTaskRelationship } from './types'

// Cloud-adapted port of desktop `useDiscussReport` / `useCreatePrReport`. These are
// task-kickoff actions (create a cloud Task linked to the report, then navigate to it) –
// NOT a live chat surface. The created task carries the SignalReport linkage so the
// backend's agent pipeline can pick it up.

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

function buildDiscussReportPrompt(report: SignalReport, question?: string): string {
    const base = `Discuss PostHog Inbox report "${report.title ?? report.id}" (id ${report.id}). Investigate the contributing findings and help the user understand and decide what to do.${
        report.summary ? `\n\nReport summary:\n${report.summary}` : ''
    }`
    const trimmed = question?.trim()
    if (!trimmed) {
        return base
    }
    return `${base}\n\nThe user asks:\n${trimmed}`
}

async function createReportTask(
    report: SignalReport,
    relationship: SignalReportTaskRelationship,
    prompt: string,
    fallbackTitle: string
): Promise<void> {
    // Pick a default repository (mirrors desktop resolving lastUsedCloudRepository → first repo).
    let repository: string | undefined
    try {
        const { repositories } = await api.tasks.repositories()
        repository = repositories[0]
    } catch {
        repository = undefined
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
        discussReport: (report: SignalReport, question?: string) => ({ report, question }),
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
        discussReport: async ({ report, question }) => {
            try {
                await createReportTask(report, 'research', buildDiscussReportPrompt(report, question), 'Discuss report')
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
                    'Implement report fix'
                )
                actions.createPrSuccess()
            } catch (error: any) {
                lemonToast.error(error?.detail || error?.message || 'Failed to start PR task')
                actions.createPrFailure()
            }
        },
    })),
])
