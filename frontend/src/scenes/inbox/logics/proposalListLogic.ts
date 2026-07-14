import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api, { CountedPaginatedResponse } from 'lib/api'
import { urls } from 'scenes/urls'

import { OriginProduct } from 'products/posthog_ai/frontend/types/taskTypes'

import { captureInboxReportAction } from '../inboxAnalytics'
import { SIGNAL_REPORT_TASK_IMPLEMENTATION_RELATIONSHIP, SignalReport } from '../types'
import { DismissalReasonValue } from '../utils/dismissalReasons'
import type { proposalListLogicType } from './proposalListLogicType'

// The setup audit files at most one proposal per category (4 today); a small page covers it.
const PROPOSAL_PAGE_SIZE = 10

// `repo_selection` is one of the first artefacts written on a proposal report, and proposals
// carry only a handful of artefacts — a small page is guaranteed to include it.
const REPO_SELECTION_ARTEFACT_FETCH_LIMIT = 100

function buildProposalPrPrompt(report: SignalReport): string {
    return (
        `Implement the approved PostHog setup-improvement proposal "${report.title ?? report.id}" ` +
        `(inbox report id ${report.id}). The proposal:\n\n${report.summary ?? ''}\n\n` +
        `The user has approved this proposal from their PostHog inbox, so implement exactly what it ` +
        `describes: integrate the PostHog capability in this repository, wire it into the real code ` +
        `paths it names, and open a PR. Create any PostHog-side resources the proposal mentions ` +
        `(insights, dashboards, funnels) via your PostHog MCP tools and link them in the PR description.`
    )
}

/**
 * Setup-improvement proposals for the inbox cold start: reports carrying a `proposal` artefact,
 * rendered only when the Reports tab is otherwise empty. Deliberately separate from
 * `reportListLogic` — that logic layers the user's reviewer scope (For-you) onto every request,
 * which would hide proposals since they have no suggested reviewers.
 */
export const proposalListLogic = kea<proposalListLogicType>([
    path(['scenes', 'inbox', 'logics', 'proposalListLogic']),

    actions({
        ensureLoaded: true,
        approveProposal: (report: SignalReport) => ({ report }),
        approveProposalSuccess: (reportId: string) => ({ reportId }),
        approveProposalFailure: (reportId: string) => ({ reportId }),
        dismissProposal: (reportId: string, reason: DismissalReasonValue, note: string) => ({
            reportId,
            reason,
            note,
        }),
        removeProposal: (reportId: string) => ({ reportId }),
    }),

    loaders(() => ({
        proposalsResponse: [
            null as CountedPaginatedResponse<SignalReport> | null,
            {
                loadProposals: async () => {
                    return await api.signalReports.list({
                        has_proposal: 'true',
                        status: 'ready',
                        limit: PROPOSAL_PAGE_SIZE,
                        ordering: 'created_at',
                    })
                },
            },
        ],
    })),

    reducers({
        proposalsResponse: {
            // Optimistic removal on dismiss; approve keeps the card (its button shows a spinner
            // until navigation) so a failed task creation doesn't lose the proposal.
            removeProposal: (state, { reportId }) =>
                state
                    ? {
                          ...state,
                          results: state.results.filter((r) => r.id !== reportId),
                          count: Math.max(0, state.count - 1),
                      }
                    : state,
        },
        approvingReportId: [
            null as string | null,
            {
                approveProposal: (_, { report }) => report.id,
                approveProposalSuccess: () => null,
                approveProposalFailure: () => null,
            },
        ],
    }),

    selectors({
        proposals: [
            (s) => [s.proposalsResponse],
            (proposalsResponse: CountedPaginatedResponse<SignalReport> | null): SignalReport[] =>
                proposalsResponse?.results ?? [],
        ],
        isLoaded: [(s) => [s.proposalsResponse], (proposalsResponse): boolean => proposalsResponse !== null],
    }),

    listeners(({ actions, values }) => ({
        ensureLoaded: () => {
            if (values.proposalsResponse === null && !values.proposalsResponseLoading) {
                actions.loadProposals()
            }
        },
        approveProposal: async ({ report }) => {
            try {
                // Proposals are created with a preset `repo_selection` artefact (the repo the
                // wizard integrated), the same source the regular create-PR flow reads.
                const { results } = await api.signalReports.artefacts(report.id, {
                    limit: REPO_SELECTION_ARTEFACT_FETCH_LIMIT,
                })
                const repository = results.find((a) => a.type === 'repo_selection')?.content?.repository
                if (typeof repository !== 'string' || !repository) {
                    throw new Error('This proposal has no target repository yet — try again in a moment.')
                }
                const task = await api.tasks.create({
                    title: report.title?.trim() || 'Implement setup proposal',
                    description: buildProposalPrPrompt(report),
                    origin_product: OriginProduct.SIGNAL_REPORT,
                    repository,
                    signal_report: report.id,
                    signal_report_task_relationship: SIGNAL_REPORT_TASK_IMPLEMENTATION_RELATIONSHIP,
                } as Parameters<typeof api.tasks.create>[0])
                captureInboxReportAction({ report, actionType: 'create_pr', surface: 'list_row' })
                actions.approveProposalSuccess(report.id)
                router.actions.push(urls.taskDetail(task.id))
            } catch (error: any) {
                lemonToast.error(error?.detail || error?.message || 'Failed to start the proposal PR')
                actions.approveProposalFailure(report.id)
            }
        },
        dismissProposal: async ({ reportId, reason, note }) => {
            const report = values.proposals.find((r) => r.id === reportId)
            actions.removeProposal(reportId)
            captureInboxReportAction({
                report: report ?? null,
                actionType: 'dismiss',
                surface: 'list_row',
                extra: { dismissal_reason: reason, ...(note ? { dismissal_note: note } : {}) },
            })
            try {
                await api.signalReports.setState(reportId, {
                    state: 'suppressed',
                    dismissal_reason: reason,
                    ...(note ? { dismissal_note: note } : {}),
                })
            } catch (error: any) {
                lemonToast.error(error?.detail || error?.message || 'Failed to dismiss proposal')
                actions.loadProposals()
            }
        },
    })),

    events(({ actions }) => ({
        afterMount: () => {
            actions.ensureLoaded()
        },
    })),
])
