import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import {
    signalsPlansFinishCreate,
    signalsPlansStartImplementationCreate,
    signalsReportArtefactsCreate,
    signalsReportsPartialUpdate,
} from 'products/signals/frontend/generated/api'

import { inboxSceneLogic } from '../inboxSceneLogic'
import { SignalReport, SignalReportArtefact, SignalScoutConfig } from '../types'
import { inboxReportDetailLogic } from './inboxReportDetailLogic'
import type { planDetailLogicType } from './planDetailLogicType'

export type PlanDetailSubTab = 'status' | 'owner' | 'feed'

/** How often a draft plan refreshes its artefacts + report while the planning agent works. */
const DRAFT_POLL_INTERVAL_MS = 2000

/** The plan's owner scout skill name — must mirror `owner_scout_skill_name` in plan_mode/service.py. */
export function ownerScoutSkillName(reportId: string): string {
    return `signals-scout-plan-${reportId.split('-')[0]}`
}

/** The report fields editable in place on the plan Status tab. */
export type PlanEditableField = 'title' | 'summary'

export interface PlanDetailLogicProps {
    reportId: string
    report: SignalReport
}

/**
 * Plan detail view state: the active sub-tab (Status / Owner / Feed), the click-to-edit surfaces for
 * the report's title/summary, and answering question artefacts. Artefact data comes from the
 * connected `inboxReportDetailLogic` (same key), so the plan view shares its loading and polling
 * with the rest of the inbox detail machinery.
 */
export const planDetailLogic = kea<planDetailLogicType>([
    path((key) => ['scenes', 'inbox', 'logics', 'planDetailLogic', key]),
    props({} as PlanDetailLogicProps),
    key((props) => props.reportId),

    connect((props: PlanDetailLogicProps) => ({
        values: [inboxReportDetailLogic(props), ['reportArtefacts', 'primaryTask'], teamLogic, ['currentProjectId']],
        actions: [
            inboxReportDetailLogic(props),
            ['loadReportArtefacts', 'loadReportArtefactsSuccess'],
            inboxSceneLogic,
            ['seedSelectedReport', 'loadSelectedReport'],
        ],
    })),

    loaders(({ props }) => ({
        // The plan's owner scout config, resolved by its deterministic skill name. Whether the
        // scout was created by the planning agent (via MCP) or by finish_plan's backstop, the name
        // is a pure function of the report id, so this lookup is the ownership link.
        ownerScoutConfig: [
            null as SignalScoutConfig | null,
            {
                loadOwnerScoutConfig: async () => {
                    const configs = await api.signalScout.configs.list()
                    return configs.find((c) => c.skill_name === ownerScoutSkillName(props.reportId)) ?? null
                },
            },
        ],
    })),

    actions({
        setActiveSubTab: (subTab: PlanDetailSubTab) => ({ subTab }),
        // Report title/summary click-to-edit.
        startEditingField: (field: PlanEditableField, initial: string) => ({ field, initial }),
        setFieldDraft: (draft: string) => ({ draft }),
        cancelEditingField: true,
        saveField: true,
        setFieldSaving: (saving: boolean) => ({ saving }),
        // Question answering.
        startAnswering: (artefactId: string) => ({ artefactId }),
        setAnswerDraft: (draft: string) => ({ draft }),
        cancelAnswering: true,
        saveAnswer: true,
        setAnswerSaving: (saving: boolean) => ({ saving }),
        // User feedback: `question` artefacts authored by the user (attribution = user id), which
        // the owner scout acts on and answers on its next run.
        setFeedbackDraft: (draft: string) => ({ draft }),
        saveFeedback: true,
        saveFeedbackSuccess: true,
        setFeedbackSaving: (saving: boolean) => ({ saving }),
        // Finalize the draft plan (defaults + backing signal + owner scout).
        finishPlan: true,
        setFinishing: (finishing: boolean) => ({ finishing }),
        // Manually start an implementation pass (shown when the plan has none yet).
        startImplementation: true,
        setStartingImplementation: (starting: boolean) => ({ starting }),
    }),

    reducers({
        activeSubTab: [
            'status' as PlanDetailSubTab,
            {
                setActiveSubTab: (_, { subTab }) => subTab,
            },
        ],
        editingField: [
            null as PlanEditableField | null,
            {
                startEditingField: (_, { field }) => field,
                cancelEditingField: () => null,
            },
        ],
        fieldDraft: [
            '',
            {
                startEditingField: (_, { initial }) => initial,
                setFieldDraft: (_, { draft }) => draft,
                cancelEditingField: () => '',
            },
        ],
        fieldSaving: [
            false,
            {
                setFieldSaving: (_, { saving }) => saving,
            },
        ],
        answeringQuestionId: [
            null as string | null,
            {
                startAnswering: (_, { artefactId }) => artefactId,
                cancelAnswering: () => null,
            },
        ],
        answerDraft: [
            '',
            {
                startAnswering: () => '',
                setAnswerDraft: (_, { draft }) => draft,
                cancelAnswering: () => '',
            },
        ],
        answerSaving: [
            false,
            {
                setAnswerSaving: (_, { saving }) => saving,
            },
        ],
        feedbackDraft: [
            '',
            {
                setFeedbackDraft: (_, { draft }) => draft,
                saveFeedbackSuccess: () => '',
            },
        ],
        feedbackSaving: [
            false,
            {
                setFeedbackSaving: (_, { saving }) => saving,
            },
        ],
        finishing: [
            false,
            {
                setFinishing: (_, { finishing }) => finishing,
            },
        ],
        startingImplementation: [
            false,
            {
                setStartingImplementation: (_, { starting }) => starting,
            },
        ],
    }),

    selectors({
        questionArtefacts: [
            (s) => [s.reportArtefacts],
            (reportArtefacts: SignalReportArtefact[] | null): SignalReportArtefact[] =>
                (reportArtefacts ?? []).filter((a) => a.type === 'question'),
        ],
        /**
         * A question's direction is its attribution: `created_by` set → from the user (feedback, for
         * an agent to answer); otherwise (task/system attributed) → from an agent, for the user.
         */
        openQuestions: [
            (s) => [s.questionArtefacts],
            (questionArtefacts: SignalReportArtefact[]): SignalReportArtefact[] =>
                questionArtefacts.filter((a) => !a.content?.answered && !a.created_by),
        ],
        outstandingFeedback: [
            (s) => [s.questionArtefacts],
            (questionArtefacts: SignalReportArtefact[]): SignalReportArtefact[] =>
                questionArtefacts.filter((a) => !a.content?.answered && !!a.created_by),
        ],
        answeredQuestions: [
            (s) => [s.questionArtefacts],
            (questionArtefacts: SignalReportArtefact[]): SignalReportArtefact[] =>
                questionArtefacts.filter((a) => !!a.content?.answered),
        ],
        /**
         * A plan is a draft until it is finished. The lifecycle marker is the `safety_judgment`
         * artefact: the planning flow never writes one, `finish_plan` always does. Null until the
         * artefact log has loaded (unknown).
         */
        isDraft: [
            (s) => [s.reportArtefacts],
            (reportArtefacts: SignalReportArtefact[] | null): boolean | null =>
                reportArtefacts === null ? null : !reportArtefacts.some((a) => a.type === 'safety_judgment'),
        ],
        /** Whether any implementation pass has been recorded on the plan (a signals/implementation task_run artefact). */
        hasImplementationRun: [
            (s) => [s.reportArtefacts],
            (reportArtefacts: SignalReportArtefact[] | null): boolean | null =>
                reportArtefacts === null
                    ? null
                    : reportArtefacts.some(
                          (a) =>
                              a.type === 'task_run' &&
                              a.content?.product === 'signals' &&
                              a.content?.type === 'implementation'
                      ),
        ],
        /** What still blocks Finish plan — mirrors the backend's readiness labels. */
        missingForFinish: [
            (s) => [s.reportArtefacts, (_, props: PlanDetailLogicProps) => props.report],
            (reportArtefacts: SignalReportArtefact[] | null, report: SignalReport): string[] => {
                const missing: string[] = []
                if (!report.title?.trim()) {
                    missing.push('title')
                }
                if (!report.summary?.trim()) {
                    missing.push('summary')
                }
                const types = new Set((reportArtefacts ?? []).map((a) => a.type))
                if (!types.has('repo_selection')) {
                    missing.push('repository selection')
                }
                if (!types.has('suggested_reviewers')) {
                    missing.push('owners')
                }
                if (!types.has('priority_judgment')) {
                    missing.push('priority')
                }
                return missing
            },
        ],
    }),

    listeners(({ actions, values, props, cache }) => ({
        // While the plan is a draft, the agent is writing to it from the sandbox — poll the artefact
        // log and the report itself so the left column refreshes live. Armed/disarmed on every
        // artefact load, so finishing the plan (or opening a finished plan) tears the interval down.
        loadReportArtefactsSuccess: () => {
            if (values.isDraft) {
                cache.disposables.add(() => {
                    const interval = setInterval(() => {
                        actions.loadReportArtefacts()
                        actions.loadSelectedReport({ id: props.reportId })
                        actions.loadOwnerScoutConfig()
                    }, DRAFT_POLL_INTERVAL_MS)
                    return () => clearInterval(interval)
                }, 'planDraftPoll')
            } else {
                cache.disposables.dispose('planDraftPoll')
            }
        },
        finishPlan: async () => {
            if (values.finishing) {
                return
            }
            actions.setFinishing(true)
            try {
                await signalsPlansFinishCreate(String(values.currentProjectId), props.reportId)
                lemonToast.success('Plan created')
                actions.loadReportArtefacts()
                actions.loadSelectedReport({ id: props.reportId })
                actions.loadOwnerScoutConfig()
                router.actions.push(urls.inboxReport('plan', props.reportId))
            } catch (error: any) {
                const missing: string[] | undefined = error?.data?.missing
                lemonToast.error(
                    missing?.length
                        ? `The plan still needs: ${missing.join(', ')}`
                        : error?.detail || error?.message || 'Failed to finish plan'
                )
            } finally {
                actions.setFinishing(false)
            }
        },
        startImplementation: async () => {
            if (values.startingImplementation) {
                return
            }
            actions.setStartingImplementation(true)
            try {
                await signalsPlansStartImplementationCreate(String(values.currentProjectId), props.reportId)
                lemonToast.success('Implementation pass started')
                actions.loadReportArtefacts()
            } catch (error: any) {
                lemonToast.error(error?.detail || error?.message || 'Failed to start implementation')
            } finally {
                actions.setStartingImplementation(false)
            }
        },
        saveField: async () => {
            const field = values.editingField
            if (!field || values.fieldSaving) {
                return
            }
            const draft = values.fieldDraft.trim()
            if (!draft) {
                lemonToast.error(`The ${field} cannot be empty`)
                return
            }
            actions.setFieldSaving(true)
            try {
                const updated = await signalsReportsPartialUpdate(String(values.currentProjectId), props.reportId, {
                    [field]: draft,
                })
                // Refresh the scene's copy so the header/list reflect the edit without a reload, and the
                // artefact log so the title_change/summary_change history entry appears in the feed.
                actions.seedSelectedReport({ ...props.report, title: updated.title, summary: updated.summary })
                actions.loadReportArtefacts()
                actions.cancelEditingField()
            } catch (error: any) {
                lemonToast.error(error?.detail || error?.message || `Failed to save ${field}`)
            } finally {
                actions.setFieldSaving(false)
            }
        },
        saveFeedback: async () => {
            if (values.feedbackSaving) {
                return
            }
            const question = values.feedbackDraft.trim()
            if (!question) {
                lemonToast.error('The feedback cannot be empty')
                return
            }
            actions.setFeedbackSaving(true)
            try {
                // Attribution (this user) is what marks the question as human→agent feedback.
                await signalsReportArtefactsCreate(String(values.currentProjectId), props.reportId, {
                    artefact_type: 'question',
                    content: { question },
                })
                actions.saveFeedbackSuccess()
                actions.loadReportArtefacts()
                lemonToast.success('Feedback added — the owner scout will answer it on its next run')
            } catch (error: any) {
                lemonToast.error(error?.detail || error?.message || 'Failed to add feedback')
            } finally {
                actions.setFeedbackSaving(false)
            }
        },
        saveAnswer: async () => {
            const artefactId = values.answeringQuestionId
            if (!artefactId || values.answerSaving) {
                return
            }
            const draft = values.answerDraft.trim()
            if (!draft) {
                lemonToast.error('The answer cannot be empty')
                return
            }
            const artefact = values.questionArtefacts.find((a) => a.id === artefactId)
            actions.setAnswerSaving(true)
            try {
                await api.signalReports.updateArtefact(props.reportId, artefactId, {
                    ...artefact?.content,
                    answer: draft,
                    answered: true,
                })
                actions.loadReportArtefacts()
                actions.cancelAnswering()
            } catch (error: any) {
                lemonToast.error(error?.detail || error?.message || 'Failed to save answer')
            } finally {
                actions.setAnswerSaving(false)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadOwnerScoutConfig()
    }),
])
