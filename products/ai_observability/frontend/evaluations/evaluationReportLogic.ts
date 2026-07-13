import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import {
    llmAnalyticsEvaluationReportsCreate,
    llmAnalyticsEvaluationReportsGenerateCreate,
    llmAnalyticsEvaluationReportsList,
    llmAnalyticsEvaluationReportsPartialUpdate,
    llmAnalyticsEvaluationReportsRunsList,
} from '../generated/api'
import type { evaluationReportLogicType } from './evaluationReportLogicType'
import type {
    EvaluationReport,
    EvaluationReportDeliveryTarget,
    EvaluationReportFrequency,
    EvaluationReportRun,
} from './types'

type EvaluationReportCreateBody = Parameters<typeof llmAnalyticsEvaluationReportsCreate>[1]
type EvaluationReportPatchBody = Parameters<typeof llmAnalyticsEvaluationReportsPartialUpdate>[2]

export interface EvaluationReportLogicProps {
    evaluationId: string
}

export type ReportScheduleCadence = 'daily' | 'weekly'
export type ReportScheduleWeekday = 'MO' | 'TU' | 'WE' | 'TH' | 'FR' | 'SA' | 'SU'

/** Draft state for the report config form — used for both the create-new-evaluation path
 * (keyed as 'new') and the edit-existing-evaluation path (keyed by the real evaluation id). */
export interface ReportConfigDraft {
    enabled: boolean
    frequency: EvaluationReportFrequency
    scheduleCadence: ReportScheduleCadence
    scheduleWeekdays: ReportScheduleWeekday[]
    emailValue: string
    slackIntegrationId: number | null
    slackChannelValue: string
    reportPromptGuidance: string
    triggerThreshold: number
    cooldownHours: number
}

export const TRIGGER_THRESHOLD_MIN = 100
export const TRIGGER_THRESHOLD_DEFAULT = 100
export const TRIGGER_THRESHOLD_MAX = 10_000
export const COOLDOWN_HOURS_DEFAULT = 1
export const COOLDOWN_HOURS_MIN = 1
export const COOLDOWN_HOURS_MAX = 24
export const DEFAULT_RRULE = 'FREQ=DAILY'
export const DEFAULT_SCHEDULE_CADENCE: ReportScheduleCadence = 'daily'
export const DEFAULT_WEEKLY_DAYS: ReportScheduleWeekday[] = ['MO']
export const WEEKDAY_OPTIONS: { value: ReportScheduleWeekday; label: string }[] = [
    { value: 'MO', label: 'Mon' },
    { value: 'TU', label: 'Tue' },
    { value: 'WE', label: 'Wed' },
    { value: 'TH', label: 'Thu' },
    { value: 'FR', label: 'Fri' },
    { value: 'SA', label: 'Sat' },
    { value: 'SU', label: 'Sun' },
]

const WEEKDAY_ORDER = WEEKDAY_OPTIONS.map((option) => option.value)

const DEFAULT_CONFIG_DRAFT: ReportConfigDraft = {
    enabled: true,
    frequency: 'every_n',
    scheduleCadence: DEFAULT_SCHEDULE_CADENCE,
    scheduleWeekdays: DEFAULT_WEEKLY_DAYS,
    emailValue: '',
    slackIntegrationId: null,
    slackChannelValue: '',
    reportPromptGuidance: '',
    triggerThreshold: TRIGGER_THRESHOLD_DEFAULT,
    cooldownHours: COOLDOWN_HOURS_DEFAULT,
}

function normalizeScheduleWeekdays(weekdays: ReportScheduleWeekday[]): ReportScheduleWeekday[] {
    const selected = new Set(weekdays)
    const normalized = WEEKDAY_ORDER.filter((weekday) => selected.has(weekday))
    return normalized.length > 0 ? normalized : DEFAULT_WEEKLY_DAYS
}

function rruleFromSchedule(cadence: ReportScheduleCadence, weekdays: ReportScheduleWeekday[]): string {
    if (cadence === 'daily') {
        return DEFAULT_RRULE
    }
    return `FREQ=WEEKLY;BYDAY=${normalizeScheduleWeekdays(weekdays).join(',')}`
}

function scheduleFromRrule(rrule: string): {
    cadence: ReportScheduleCadence
    weekdays: ReportScheduleWeekday[]
} {
    if (rrule.startsWith('FREQ=WEEKLY')) {
        const byday = rrule
            .split(';')
            .find((part) => part.startsWith('BYDAY='))
            ?.replace('BYDAY=', '')
        const weekdays = normalizeScheduleWeekdays(
            (byday?.split(',') ?? []).filter((day): day is ReportScheduleWeekday =>
                WEEKDAY_ORDER.includes(day as ReportScheduleWeekday)
            )
        )
        return { cadence: 'weekly', weekdays }
    }
    return { cadence: 'daily', weekdays: DEFAULT_WEEKLY_DAYS }
}

function draftFromReport(report: EvaluationReport): ReportConfigDraft {
    const emailTarget = report.delivery_targets.find((t) => t.type === 'email')
    const slackTarget = report.delivery_targets.find((t) => t.type === 'slack')
    const schedule = scheduleFromRrule(report.rrule ?? '')
    // Normalise here so the dirty check (which compares against draft.emailValue
    // that buildDeliveryTargets later trims) doesn't fire a false positive when
    // the stored value is surrounded by whitespace.
    return {
        enabled: report.enabled,
        frequency: report.frequency,
        scheduleCadence: schedule.cadence,
        scheduleWeekdays: schedule.weekdays,
        emailValue: (emailTarget?.value ?? '').trim(),
        slackIntegrationId: slackTarget?.integration_id ?? null,
        slackChannelValue: slackTarget?.channel ?? '',
        reportPromptGuidance: report.report_prompt_guidance ?? '',
        triggerThreshold: report.trigger_threshold ?? TRIGGER_THRESHOLD_DEFAULT,
        cooldownHours: Math.max(1, Math.round((report.cooldown_minutes ?? COOLDOWN_HOURS_DEFAULT * 60) / 60)),
    }
}

export function buildDeliveryTargets(draft: ReportConfigDraft): EvaluationReportDeliveryTarget[] {
    const targets: EvaluationReportDeliveryTarget[] = []
    const email = draft.emailValue.trim()
    if (email.length > 0) {
        targets.push({ type: 'email', value: email })
    }
    if (draft.slackIntegrationId !== null && draft.slackChannelValue.length > 0) {
        targets.push({
            type: 'slack',
            integration_id: draft.slackIntegrationId,
            channel: draft.slackChannelValue,
        })
    }
    return targets
}

function buildReportUpdatePayload(
    draft: ReportConfigDraft,
    activeReport: EvaluationReport,
    targets: EvaluationReportDeliveryTarget[]
): Record<string, unknown> {
    const data: Record<string, unknown> = {
        enabled: draft.enabled,
        frequency: draft.frequency,
        delivery_targets: targets,
        report_prompt_guidance: draft.reportPromptGuidance,
    }
    if (draft.frequency === 'scheduled') {
        data.rrule = rruleFromSchedule(draft.scheduleCadence, draft.scheduleWeekdays)
    }
    if (draft.frequency === 'every_n') {
        data.trigger_threshold = draft.triggerThreshold
        // Only write cooldown_minutes back when the user changed it — the draft rounds
        // minutes to hours for display, so unconditionally writing (hours * 60) would
        // silently clobber sub-hour values set via the API (e.g. 89 min → 60 min).
        const seededCooldownHours = Math.max(1, Math.round((activeReport.cooldown_minutes ?? 60) / 60))
        if (draft.cooldownHours !== seededCooldownHours) {
            data.cooldown_minutes = draft.cooldownHours * 60
        }
    }
    return data
}

function buildReportCreatePayload(
    draft: ReportConfigDraft,
    evaluationId: string,
    targets: EvaluationReportDeliveryTarget[]
): Record<string, unknown> {
    const body: Record<string, unknown> = {
        evaluation: evaluationId,
        frequency: draft.frequency,
        delivery_targets: targets,
        report_prompt_guidance: draft.reportPromptGuidance,
        enabled: draft.enabled,
    }
    if (draft.frequency === 'scheduled') {
        body.rrule = rruleFromSchedule(draft.scheduleCadence, draft.scheduleWeekdays)
    }
    if (draft.frequency === 'every_n') {
        body.trigger_threshold = draft.triggerThreshold
        body.cooldown_minutes = draft.cooldownHours * 60
    }
    return body
}

async function loadReportsForEvaluation(teamId: number, evaluationId: string): Promise<EvaluationReport[]> {
    const response = await llmAnalyticsEvaluationReportsList(teamId.toString(), { evaluation: evaluationId })
    return (response.results || []) as EvaluationReport[]
}

function requireCurrentTeamId(teamId: number | null): number {
    if (teamId === null) {
        throw new Error('Current team is not loaded')
    }
    return teamId
}

/** Inline persistor used by the parent evaluation save flow so the single
 * "Save changes" button at the top of the page commits both the evaluation
 * and the (optional) scheduled report. Mirrors the saveDraft listener but
 * bypasses the loader plumbing so callers can await the network write.
 *
 * Returns true if a network write was performed. */
export async function persistReportDraft(
    teamId: number,
    evaluationId: string,
    draft: ReportConfigDraft,
    activeReport: EvaluationReport | null
): Promise<boolean> {
    const targets = buildDeliveryTargets(draft)
    if (activeReport) {
        await llmAnalyticsEvaluationReportsPartialUpdate(
            teamId.toString(),
            activeReport.id,
            buildReportUpdatePayload(draft, activeReport, targets) as EvaluationReportPatchBody
        )
        return true
    }

    await llmAnalyticsEvaluationReportsCreate(
        teamId.toString(),
        buildReportCreatePayload(draft, evaluationId, targets) as EvaluationReportCreateBody
    )
    return true
}

export const evaluationReportLogic = kea<evaluationReportLogicType>([
    path(['products', 'ai_observability', 'frontend', 'evaluations', 'evaluationReportLogic']),
    props({} as EvaluationReportLogicProps),
    key((props) => props.evaluationId),
    connect({
        values: [teamLogic, ['currentTeamId']],
    }),

    actions({
        setDraftEnabled: (enabled: boolean) => ({ enabled }),
        setDraftFrequency: (frequency: EvaluationReportFrequency) => ({ frequency }),
        setDraftScheduleCadence: (cadence: ReportScheduleCadence) => ({ cadence }),
        toggleDraftScheduleWeekday: (weekday: ReportScheduleWeekday) => ({ weekday }),
        setDraftEmailValue: (emailValue: string) => ({ emailValue }),
        setDraftSlackIntegrationId: (integrationId: number | null) => ({ integrationId }),
        setDraftSlackChannelValue: (channelValue: string) => ({ channelValue }),
        setDraftReportPromptGuidance: (reportPromptGuidance: string) => ({ reportPromptGuidance }),
        setDraftTriggerThreshold: (triggerThreshold: number) => ({ triggerThreshold }),
        setDraftCooldownHours: (cooldownHours: number) => ({ cooldownHours }),
        seedDraftFromReport: (report: EvaluationReport) => ({ report }),
        resetDraft: true,

        /** Save the current draft against the active report — creates if none exists, updates otherwise. */
        saveDraft: true,

        selectReportRun: (reportRun: EvaluationReportRun | null) => ({ reportRun }),
    }),

    reducers({
        configDraft: [
            DEFAULT_CONFIG_DRAFT as ReportConfigDraft,
            {
                setDraftEnabled: (state, { enabled }) => ({ ...state, enabled }),
                setDraftFrequency: (state, { frequency }) => {
                    return { ...state, frequency }
                },
                setDraftScheduleCadence: (state, { cadence }) => ({
                    ...state,
                    scheduleCadence: cadence,
                }),
                toggleDraftScheduleWeekday: (state, { weekday }) => {
                    const existing = new Set(state.scheduleWeekdays)
                    if (existing.has(weekday)) {
                        existing.delete(weekday)
                    } else {
                        existing.add(weekday)
                    }
                    const scheduleWeekdays = normalizeScheduleWeekdays([...existing])
                    return {
                        ...state,
                        scheduleWeekdays,
                    }
                },
                setDraftEmailValue: (state, { emailValue }) => ({ ...state, emailValue }),
                setDraftSlackIntegrationId: (state, { integrationId }) => ({
                    ...state,
                    slackIntegrationId: integrationId,
                    // Clear channel when switching Slack workspaces so we don't send a
                    // channel id from a different workspace.
                    slackChannelValue: integrationId !== state.slackIntegrationId ? '' : state.slackChannelValue,
                }),
                setDraftSlackChannelValue: (state, { channelValue }) => ({
                    ...state,
                    slackChannelValue: channelValue,
                }),
                setDraftReportPromptGuidance: (state, { reportPromptGuidance }) => ({
                    ...state,
                    reportPromptGuidance,
                }),
                setDraftTriggerThreshold: (state, { triggerThreshold }) => ({
                    ...state,
                    triggerThreshold,
                }),
                setDraftCooldownHours: (state, { cooldownHours }) => ({
                    ...state,
                    cooldownHours,
                }),
                seedDraftFromReport: (_, { report }) => draftFromReport(report),
                resetDraft: () => DEFAULT_CONFIG_DRAFT,
            },
        ],
        selectedReportRun: [
            null as EvaluationReportRun | null,
            {
                selectReportRun: (_, { reportRun }) => reportRun,
            },
        ],
    }),

    loaders(({ props, values }) => ({
        reports: [
            [] as EvaluationReport[],
            {
                loadReports: async () => {
                    if (props.evaluationId === 'new') {
                        return []
                    }
                    return loadReportsForEvaluation(requireCurrentTeamId(values.currentTeamId), props.evaluationId)
                },
                createReport: async (params: {
                    evaluationId: string
                    enabled: boolean
                    frequency: EvaluationReportFrequency
                    rrule?: string
                    delivery_targets: EvaluationReportDeliveryTarget[]
                    report_prompt_guidance?: string
                    trigger_threshold?: number | null
                    cooldown_minutes?: number | null
                }) => {
                    const body: Record<string, unknown> = {
                        evaluation: params.evaluationId,
                        frequency: params.frequency,
                        delivery_targets: params.delivery_targets,
                        report_prompt_guidance: params.report_prompt_guidance ?? '',
                        enabled: params.enabled,
                    }
                    if (params.frequency === 'scheduled') {
                        body.rrule = params.rrule ?? ''
                    }
                    if (params.frequency === 'every_n' && params.trigger_threshold != null) {
                        body.trigger_threshold = params.trigger_threshold
                    }
                    if (params.frequency === 'every_n' && params.cooldown_minutes != null) {
                        body.cooldown_minutes = params.cooldown_minutes
                    }
                    const teamId = requireCurrentTeamId(values.currentTeamId)
                    const report = await llmAnalyticsEvaluationReportsCreate(
                        teamId.toString(),
                        body as EvaluationReportCreateBody
                    )
                    return [
                        ...values.reports.filter((existing) => existing.id !== report.id),
                        report as EvaluationReport,
                    ]
                },
                updateReport: async ({ reportId, data }: { reportId: string; data: Partial<EvaluationReport> }) => {
                    const teamId = requireCurrentTeamId(values.currentTeamId)
                    const updated = await llmAnalyticsEvaluationReportsPartialUpdate(
                        teamId.toString(),
                        reportId,
                        data as EvaluationReportPatchBody
                    )
                    return values.reports.map((r) => (r.id === reportId ? (updated as EvaluationReport) : r))
                },
            },
        ],
        reportRuns: [
            [] as EvaluationReportRun[],
            {
                loadReportRuns: async (reportId: string) => {
                    const teamId = requireCurrentTeamId(values.currentTeamId)
                    const response = await llmAnalyticsEvaluationReportsRunsList(teamId.toString(), reportId)
                    // The runs endpoint is paginated (DRF envelope); unwrap results so the
                    // reducer gets an array rather than the {count, next, previous, results} object.
                    return (response?.results || []) as unknown as EvaluationReportRun[]
                },
            },
        ],
        generateResult: [
            null as null,
            {
                generateReport: async (reportId: string) => {
                    const teamId = requireCurrentTeamId(values.currentTeamId)
                    await llmAnalyticsEvaluationReportsGenerateCreate(teamId.toString(), reportId)
                    return null
                },
            },
        ],
    })),

    selectors({
        isNewEvaluation: [(_, p) => [p.evaluationId], (evaluationId: string) => evaluationId === 'new'],
        activeReport: [
            (s) => [s.reports],
            (reports): EvaluationReport | null => {
                return reports.find((r: EvaluationReport) => !r.deleted) || null
            },
        ],
        isConfigDirty: [
            (s) => [s.activeReport, s.configDraft],
            (activeReport, draft): boolean => {
                if (!activeReport) {
                    // No report yet: draft is "dirty" if it has any savable content.
                    return (
                        !draft.enabled ||
                        draft.frequency !== 'every_n' ||
                        buildDeliveryTargets(draft).length > 0 ||
                        draft.reportPromptGuidance.trim().length > 0 ||
                        draft.triggerThreshold !== TRIGGER_THRESHOLD_DEFAULT ||
                        draft.cooldownHours !== COOLDOWN_HOURS_DEFAULT
                    )
                }
                const baseline = draftFromReport(activeReport)
                const scheduleDirty =
                    draft.frequency === 'scheduled' &&
                    rruleFromSchedule(baseline.scheduleCadence, baseline.scheduleWeekdays) !==
                        rruleFromSchedule(draft.scheduleCadence, draft.scheduleWeekdays)
                return (
                    baseline.enabled !== draft.enabled ||
                    baseline.frequency !== draft.frequency ||
                    baseline.emailValue !== draft.emailValue.trim() ||
                    baseline.slackIntegrationId !== draft.slackIntegrationId ||
                    baseline.slackChannelValue !== draft.slackChannelValue ||
                    baseline.reportPromptGuidance !== draft.reportPromptGuidance ||
                    (draft.frequency === 'every_n' && baseline.triggerThreshold !== draft.triggerThreshold) ||
                    (draft.frequency === 'every_n' && baseline.cooldownHours !== draft.cooldownHours) ||
                    scheduleDirty
                )
            },
        ],
    }),

    listeners(({ actions, values, props }) => ({
        loadReportsSuccess: ({ reports }) => {
            // Auto-load the run history for the saved report so the Reports tab knows
            // whether to render itself and can show data immediately.
            const active = reports.find((r: EvaluationReport) => !r.deleted)
            if (active) {
                actions.loadReportRuns(active.id)
                // Seed the draft so the config form reflects the saved report instead of defaults.
                actions.seedDraftFromReport(active)
            }
        },
        generateReportSuccess: () => {
            lemonToast.success('Report is being generated and will be delivered to your configured targets shortly.')
        },
        generateReportFailure: () => {
            lemonToast.error('Failed to trigger report generation. Please try again.')
        },
        createReportSuccess: () => {
            actions.loadReports()
        },
        updateReportSuccess: () => {
            actions.loadReports()
        },
        saveDraft: () => {
            const { configDraft, activeReport } = values
            const targets = buildDeliveryTargets(configDraft)
            if (activeReport) {
                actions.updateReport({
                    reportId: activeReport.id,
                    data: buildReportUpdatePayload(configDraft, activeReport, targets),
                })
            } else {
                actions.createReport({
                    evaluationId: props.evaluationId,
                    enabled: configDraft.enabled,
                    frequency: configDraft.frequency,
                    rrule: rruleFromSchedule(configDraft.scheduleCadence, configDraft.scheduleWeekdays),
                    delivery_targets: targets,
                    report_prompt_guidance: configDraft.reportPromptGuidance,
                    trigger_threshold: configDraft.frequency === 'every_n' ? configDraft.triggerThreshold : null,
                    cooldown_minutes: configDraft.frequency === 'every_n' ? configDraft.cooldownHours * 60 : null,
                })
            }
        },
    })),

    afterMount(({ actions, props }) => {
        if (props.evaluationId !== 'new') {
            actions.loadReports()
        }
    }),
])
