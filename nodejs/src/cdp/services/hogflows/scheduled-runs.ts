import { DateTime } from 'luxon'
import { z } from 'zod'

import { QuotaLimiting } from '~/common/services/quota-limiting.service'
import { TeamManager } from '~/common/utils/team-manager'
import { UUIDT } from '~/common/utils/utils'
import { Team } from '~/types'

import { HogFlow } from '../../schema/hogflow'
import { CyclotronJobInvocationHogFlow, HogFunctionInvocationGlobals } from '../../types'
import { convertToHogFunctionFilterGlobal } from '../../utils/hog-function-filtering'
import type { InvocationResultsService } from '../invocation-results.service'
import { JobQueue } from '../job-queue/job-queue.interface'
import { WorkflowsActivationReporter } from '../monitoring/workflows-activation-reporter'
import { createHogFlowInvocation } from './hogflow-executor.service'
import type { HogFlowManagerService } from './hogflow-manager.service'
import { shouldBlockHogFlowDueToQuota } from './hogflow-quota-limiting'

export const ScheduledRunsRequestSchema = z.object({
    runs: z.array(
        z.object({
            team_id: z.number().int(),
            hog_flow_id: z.string(),
            variables: z.record(z.string(), z.unknown()).default({}),
        })
    ),
})

export type ScheduledRunRequest = {
    teamId: number
    hogFlowId: string
    variables: Record<string, unknown>
}

export type ScheduledRunOutcome =
    | { status: 'queued'; invocationId: string }
    | { status: 'team_not_found' }
    | { status: 'workflow_not_found' }
    | { status: 'not_a_schedule_trigger' }
    | { status: 'quota_limited' }

type Admission = ScheduledRunOutcome | { status: 'admitted'; invocation: CyclotronJobInvocationHogFlow }

export type ScheduledRunsDeps = {
    siteUrl: string
    teams: Pick<TeamManager, 'getTeams'>
    hogFlows: Pick<HogFlowManagerService, 'getHogFlows'>
    queue: JobQueue
    invocationResults: InvocationResultsService
    quotaLimiting: QuotaLimiting
    workflowsActivationReporter: Pick<WorkflowsActivationReporter, 'report'>
}

export class ScheduledRuns {
    constructor(private readonly deps: ScheduledRunsDeps) {}

    async queue(requests: ScheduledRunRequest[]): Promise<ScheduledRunOutcome[]> {
        const teamIds = [...new Set(requests.map((request) => request.teamId).filter(Number.isInteger))]
        const [teams, hogFlows] = await Promise.all([
            this.deps.teams.getTeams(teamIds),
            this.deps.hogFlows.getHogFlows([...new Set(requests.map((request) => request.hogFlowId))]),
        ])
        const admissions = await Promise.all(
            requests.map((request) =>
                this.admit(request, teams[String(request.teamId)] ?? null, hogFlows[request.hogFlowId] ?? null)
            )
        )
        try {
            await this.enqueue(
                admissions.flatMap((admission) => (admission.status === 'admitted' ? [admission.invocation] : []))
            )
        } finally {
            void this.deps.invocationResults.monitoringService.flush()
        }
        return admissions.map((admission) =>
            admission.status === 'admitted' ? { status: 'queued', invocationId: admission.invocation.id } : admission
        )
    }

    private async admit(request: ScheduledRunRequest, team: Team | null, hogFlow: HogFlow | null): Promise<Admission> {
        if (!team) {
            return { status: 'team_not_found' }
        }
        if (!hogFlow || hogFlow.team_id !== team.id) {
            return { status: 'workflow_not_found' }
        }
        if (hogFlow.trigger?.type !== 'schedule') {
            return { status: 'not_a_schedule_trigger' }
        }
        const quotaLimited = await shouldBlockHogFlowDueToQuota(
            { teamId: team.id, functionId: hogFlow.id, hogFlow },
            {
                quotaLimiting: this.deps.quotaLimiting,
                hogFunctionMonitoringService: this.deps.invocationResults.monitoringService,
                workflowsActivationReporter: this.deps.workflowsActivationReporter,
            }
        )
        if (quotaLimited) {
            return { status: 'quota_limited' }
        }
        return { status: 'admitted', invocation: this.createInvocation(team, hogFlow, request.variables) }
    }

    private createInvocation(
        team: Team,
        hogFlow: HogFlow,
        variables: Record<string, unknown>
    ): CyclotronJobInvocationHogFlow {
        // Schedule triggers have no real event, but the executor reads globals.event in downstream actions.
        const syntheticEvent: HogFunctionInvocationGlobals['event'] = {
            uuid: new UUIDT().toString(),
            event: '$workflow_scheduled',
            distinct_id: `workflow-${hogFlow.id}`,
            timestamp: DateTime.now().toISO(),
            url: '',
            properties: {},
            elements_chain: '',
        }
        const triggerGlobals: HogFunctionInvocationGlobals = {
            event: syntheticEvent,
            project: { id: team.id, name: team.name, url: `${this.deps.siteUrl}/project/${team.id}` },
            variables,
        }
        const filterGlobals = convertToHogFunctionFilterGlobal({
            event: syntheticEvent,
            person: undefined,
            groups: {},
            variables,
        })
        return createHogFlowInvocation(triggerGlobals, hogFlow, filterGlobals)
    }

    private async enqueue(invocations: CyclotronJobInvocationHogFlow[]): Promise<void> {
        if (invocations.length === 0) {
            return
        }
        const rows = this.deps.invocationResults.invocationResultsRowsService
        // Queued before queueInvocations serializes the invocations, so the
        // `state.firstScheduledAt` stamp reaches cyclotron.
        invocations.forEach((invocation) => rows.queueLifecycleRow(invocation, 'running'))
        try {
            await this.deps.queue.queueInvocations(invocations)
        } catch (error) {
            rows.dropQueuedRowsFor(invocations.map((invocation) => invocation.id))
            throw error
        }
        invocations.forEach((invocation) =>
            this.deps.invocationResults.monitoringService.queueAppMetric(
                {
                    team_id: invocation.teamId,
                    app_source_id: invocation.hogFlow.id,
                    metric_kind: 'other',
                    metric_name: 'triggered',
                    count: 1,
                    app_source_version: { id: invocation.hogFlow.id, version: invocation.hogFlow.version },
                },
                'hog_flow'
            )
        )
        // Only the lifecycle sink, which swallows its own produce failures. Flushing every sink
        // would fail an enqueued run on an unrelated sink's error, and the caller would retry it.
        await rows.flush()
    }
}
