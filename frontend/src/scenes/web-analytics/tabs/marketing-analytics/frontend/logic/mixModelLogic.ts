import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import type { mixModelLogicType } from './mixModelLogicType'

// Local response types mirroring the MMM serializers in products/marketing_analytics/backend/api_mmm.py.
// The handwritten `lib/api` client is used (rather than the generated functions) so this tab builds
// without the OpenAPI codegen round-trip; once `hogli build:openapi` has run, these can be swapped for
// the generated `marketingAnalyticsMmm*` functions and `Mmm*Api` types.

export interface MmmSpendPanelRow {
    week: string
    channel: string
    spend: number
    impressions: number
    clicks: number
}

export interface MmmOutcomeRow {
    week: string
    outcome: number
    control_weekofyear: number
    is_holiday_week: boolean
}

export interface MmmDatasetResponse {
    status: string
    message: string
    date_from: string
    date_to: string
    window_weeks: number
    outcome_kind: string
    outcome_ref: string
    channels: string[]
    spend_panel: MmmSpendPanelRow[]
    spend_panel_count: number
    outcome_series: MmmOutcomeRow[]
}

export interface MmmRun {
    job_id: string
    status: string
    model_version: string
    outcome_kind: string
    outcome_ref: string
    date_from: string
    date_to: string
    window_weeks: number
    channels: string[]
    r_squared: number
    mape: number
    divergences: number
    total_budget: number
    computed_at: string
}

export interface MmmRunsResponse {
    results: MmmRun[]
}

export interface MmmContributionRow {
    week: string
    channel: string
    spend: number
    contribution: number
    contribution_lower: number
    contribution_upper: number
}

export interface MmmCurveRow {
    channel: string
    spend_point: number
    incremental_outcome: number
    incremental_lower: number
    incremental_upper: number
}

export interface MmmRoiRow {
    channel: string
    roi: number
    roi_lower: number
    roi_upper: number
    marginal_roi: number
    current_spend: number
    recommended_spend: number
    calibrated: boolean
}

export interface MmmRunDetailResponse {
    run: MmmRun | null
    contributions: MmmContributionRow[]
    curves: MmmCurveRow[]
    roi: MmmRoiRow[]
}

export interface MmmCalibration {
    channel: string
    lift_pct: number
    ci_low: number
    ci_high: number
    source?: string
    experiment_id?: string | null
}

export interface MmmCalibrationsResponse {
    calibrations: MmmCalibration[]
}

export interface CalibrationDraft {
    channel: string
    lift_pct: number | null
    ci_low: number | null
    ci_high: number | null
}

const EMPTY_DRAFT: CalibrationDraft = { channel: '', lift_pct: null, ci_low: null, ci_high: null }

const apiBase = (): string => `api/projects/${teamLogic.values.currentTeamId}/marketing_analytics`

export const mixModelLogic = kea<mixModelLogicType>([
    path(['scenes', 'webAnalytics', 'tabs', 'marketingAnalytics', 'mixModelLogic']),
    connect(() => ({ values: [teamLogic, ['currentTeamId']] })),
    actions({
        setSelectedJobId: (jobId: string | null) => ({ jobId }),
        setOutcomeIndex: (outcomeIndex: number) => ({ outcomeIndex }),
        setCalibrationDraft: (draft: Partial<CalibrationDraft>) => ({ draft }),
        submitCalibrationDraft: true,
    }),
    loaders(({ values }) => ({
        dataset: [
            null as MmmDatasetResponse | null,
            {
                loadDataset: async () =>
                    await api.get<MmmDatasetResponse>(`${apiBase()}/mmm_dataset/?outcome_index=${values.outcomeIndex}`),
            },
        ],
        runsResponse: [
            null as MmmRunsResponse | null,
            {
                loadRuns: async () => await api.get<MmmRunsResponse>(`${apiBase()}/mmm_runs/`),
            },
        ],
        runDetail: [
            null as MmmRunDetailResponse | null,
            {
                loadRunDetail: async () => {
                    const query = values.selectedJobId ? `?job_id=${values.selectedJobId}` : ''
                    return await api.get<MmmRunDetailResponse>(`${apiBase()}/mmm_run/${query}`)
                },
            },
        ],
        calibrationsResponse: [
            null as MmmCalibrationsResponse | null,
            {
                loadCalibrations: async () => await api.get<MmmCalibrationsResponse>(`${apiBase()}/mmm_calibrations/`),
                // kea-loaders creates the `saveCalibration` action from this key; the payload is the
                // calibration to upsert. POST is a full replace, so merge it into the existing set.
                saveCalibration: async (calibration: MmmCalibration) => {
                    const existing = (values.calibrationsResponse?.calibrations ?? []).filter(
                        (c) => c.channel !== calibration.channel
                    )
                    return await api.create<MmmCalibrationsResponse>(`${apiBase()}/mmm_calibrations/`, {
                        calibrations: [...existing, calibration],
                    })
                },
            },
        ],
    })),
    reducers({
        selectedJobId: [null as string | null, { setSelectedJobId: (_, { jobId }) => jobId }],
        outcomeIndex: [0, { setOutcomeIndex: (_, { outcomeIndex }) => outcomeIndex }],
        // Distinguish a read failure (e.g. S3 storage unconfigured → 503) from the "no run yet" empty
        // state, so the tab can show an accurate error instead of "trigger the Dagster job".
        runReadError: [
            null as string | null,
            {
                loadRuns: () => null,
                loadRunDetail: () => null,
                loadRunsFailure: (_, { error }) => error || 'Failed to load MMM runs.',
                loadRunDetailFailure: (_, { error }) => error || 'Failed to load the MMM run.',
            },
        ],
        calibrationDraft: [
            EMPTY_DRAFT,
            {
                setCalibrationDraft: (state, { draft }) => ({ ...state, ...draft }),
                saveCalibrationSuccess: () => EMPTY_DRAFT,
            },
        ],
    }),
    selectors({
        run: [(s) => [s.runDetail], (runDetail): MmmRun | null => runDetail?.run ?? null],
        budgetRecommendation: [
            (s) => [s.roi],
            (roi): { totalShift: number; increases: MmmRoiRow[]; decreases: MmmRoiRow[] } => {
                const increases = roi.filter((r) => r.recommended_spend > r.current_spend)
                const decreases = roi.filter((r) => r.recommended_spend < r.current_spend)
                const totalShift = increases.reduce((sum, r) => sum + (r.recommended_spend - r.current_spend), 0)
                return { totalShift, increases, decreases }
            },
        ],
        contributions: [(s) => [s.runDetail], (runDetail): MmmContributionRow[] => runDetail?.contributions ?? []],
        curves: [(s) => [s.runDetail], (runDetail): MmmCurveRow[] => runDetail?.curves ?? []],
        roi: [(s) => [s.runDetail], (runDetail): MmmRoiRow[] => runDetail?.roi ?? []],
        runs: [(s) => [s.runsResponse], (runsResponse): MmmRun[] => runsResponse?.results ?? []],
        calibrations: [
            (s) => [s.calibrationsResponse],
            (calibrationsResponse): MmmCalibration[] => calibrationsResponse?.calibrations ?? [],
        ],
        // Long → wide decomposition for the stacked-area chart: ISO week labels + one series per channel.
        decomposition: [
            (s) => [s.contributions],
            (contributions): { labels: string[]; series: { key: string; label: string; data: number[] }[] } => {
                const weeks = Array.from(new Set(contributions.map((c) => c.week))).sort()
                const channels = Array.from(new Set(contributions.map((c) => c.channel)))
                const byWeekChannel = new Map<string, number>()
                for (const row of contributions) {
                    byWeekChannel.set(`${row.week}::${row.channel}`, row.contribution)
                }
                const series = channels.map((channel) => ({
                    key: channel,
                    label: channel === '__baseline__' ? 'Baseline' : channel,
                    data: weeks.map((week) => byWeekChannel.get(`${week}::${channel}`) ?? 0),
                }))
                return { labels: weeks, series }
            },
        ],
        datasetCsvUrl: [
            (s) => [s.currentTeamId, s.outcomeIndex],
            (currentTeamId, outcomeIndex): string =>
                `/api/projects/${currentTeamId}/marketing_analytics/mmm_dataset/?format=csv&outcome_index=${outcomeIndex}`,
        ],
        isCalibrationDraftValid: [
            (s) => [s.calibrationDraft],
            (draft): boolean =>
                !!draft.channel &&
                draft.lift_pct !== null &&
                draft.ci_low !== null &&
                draft.ci_high !== null &&
                draft.ci_low <= draft.ci_high,
        ],
    }),
    listeners(({ actions, values }) => ({
        setSelectedJobId: () => actions.loadRunDetail(),
        setOutcomeIndex: () => actions.loadDataset(),
        submitCalibrationDraft: () => {
            const draft = values.calibrationDraft
            if (!values.isCalibrationDraftValid) {
                return
            }
            actions.saveCalibration({
                channel: draft.channel,
                lift_pct: draft.lift_pct as number,
                ci_low: draft.ci_low as number,
                ci_high: draft.ci_high as number,
                source: 'manual',
                experiment_id: null,
            })
        },
    })),
    afterMount(({ actions }) => {
        actions.loadDataset()
        actions.loadRuns()
        actions.loadRunDetail()
        actions.loadCalibrations()
    }),
])
