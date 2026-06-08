import {
    llmAnalyticsEvaluationReportsCreate,
    llmAnalyticsEvaluationReportsGenerateCreate,
    llmAnalyticsEvaluationReportsList,
    llmAnalyticsEvaluationReportsPartialUpdate,
    llmAnalyticsEvaluationReportsRunsList,
} from '../generated/api'
import type { EvaluationReport, EvaluationReportRun } from './types'

type EvaluationReportListParams = NonNullable<Parameters<typeof llmAnalyticsEvaluationReportsList>[1]> & {
    evaluation: string
}
export type EvaluationReportCreatePayload = Parameters<typeof llmAnalyticsEvaluationReportsCreate>[1]
type GeneratedEvaluationReportUpdatePayload = NonNullable<
    Parameters<typeof llmAnalyticsEvaluationReportsPartialUpdate>[2]
>

const evaluationReportListParams = (evaluationId: string): EvaluationReportListParams => ({ evaluation: evaluationId })

export async function loadEvaluationReportsForEvaluation(
    teamId: number | null,
    evaluationId: string
): Promise<EvaluationReport[]> {
    const response = await llmAnalyticsEvaluationReportsList(String(teamId), evaluationReportListParams(evaluationId))
    return (response?.results || []) as EvaluationReport[]
}

export async function createEvaluationReport(
    teamId: number | null,
    data: EvaluationReportCreatePayload
): Promise<EvaluationReport> {
    const report = await llmAnalyticsEvaluationReportsCreate(String(teamId), data)
    return report as EvaluationReport
}

export async function updateEvaluationReport(
    teamId: number | null,
    reportId: string,
    data: Partial<EvaluationReport>
): Promise<EvaluationReport> {
    const report = await llmAnalyticsEvaluationReportsPartialUpdate(
        String(teamId),
        reportId,
        data as GeneratedEvaluationReportUpdatePayload
    )
    return report as EvaluationReport
}

export async function loadEvaluationReportRuns(
    teamId: number | null,
    reportId: string
): Promise<EvaluationReportRun[]> {
    const response = await llmAnalyticsEvaluationReportsRunsList(String(teamId), reportId)
    return (response?.results || []) as EvaluationReportRun[]
}

export async function generateEvaluationReport(teamId: number | null, reportId: string): Promise<void> {
    await llmAnalyticsEvaluationReportsGenerateCreate(String(teamId), reportId)
}
