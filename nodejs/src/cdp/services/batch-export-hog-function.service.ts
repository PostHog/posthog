import { z } from 'zod'

import { TeamManager } from '~/utils/team-manager'

import { RawClickHouseEvent, Team } from '../../types'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { UUID, UUIDT } from '../../utils/utils'
import {
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    HogFunctionInvocationGlobals,
    HogFunctionType,
} from '../types'
import { convertToHogFunctionInvocationGlobals } from '../utils'
import { createInvocation } from '../utils/invocation-utils'
import { HogExecutorService } from './hog-executor.service'
import { InvocationResultsService } from './invocation-results.service'
import { GroupsManagerService } from './managers/groups-manager.service'
import { HogFunctionManagerService } from './managers/hog-function-manager.service'
import { HogWatcherService } from './monitoring/hog-watcher.service'

// TODO: This might be too strict so we need to validate that it matches well what we would expect to get from batch exports
const batchExportRequestBodySchema = z.object({
    clickhouse_event: z.object({
        uuid: z.string(),
        event: z.string(),
        team_id: z.number(),
        distinct_id: z.string(),
        person_id: z.string().optional(),
        timestamp: z.string(),
        captured_at: z.string().nullish(),
        properties: z.string().optional(),
        elements_chain: z.string().default(''),
        person_properties: z.string().optional(),
    }),
    invocation_id: z.guid().optional(),
})

export class BatchExportHogFunctionService {
    private promiseScheduler: PromiseScheduler

    constructor(
        private siteUrl: string,
        private teamManager: TeamManager,
        private groupsManager: GroupsManagerService,
        private hogFunctionManager: HogFunctionManagerService,
        private hogExecutor: HogExecutorService,
        private hogWatcher: HogWatcherService,
        private invocationResultsService: InvocationResultsService
    ) {
        this.promiseScheduler = new PromiseScheduler()
    }

    async execute(
        params: { team_id: string; hog_function_id: string },
        body: unknown
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
        const parsed = batchExportRequestBodySchema.safeParse(body)
        if (!parsed.success) {
            throw new ParseError('Invalid request body: ' + parsed.error.message)
        }

        const { clickhouse_event, invocation_id } = parsed.data
        const invocationId = invocation_id ? new UUID(invocation_id) : new UUIDT()

        let team: Team | null
        try {
            team = await this.teamManager.getTeam(parseInt(params.team_id))
        } catch {
            throw new ParseError('Invalid team_id: ' + params.team_id)
        }
        if (!team) {
            throw new NotFoundError('Missing team with id: ' + params.team_id)
        }

        const hogFunction = await this.hogFunctionManager.getHogFunction(params.hog_function_id)
        if (!hogFunction) {
            throw new NotFoundError('Missing hog function with id: ' + params.hog_function_id)
        }
        if (hogFunction.team_id !== team.id || !hogFunction.batch_export_id) {
            throw new NotFoundError('Missing hog function with id: ' + params.hog_function_id)
        }

        const globals = this.buildRequestGlobals(clickhouse_event as RawClickHouseEvent, hogFunction, team)
        await this.groupsManager.addGroupsToGlobals(globals)

        const globalsWithInputs = await this.hogExecutor.buildInputsWithGlobals(hogFunction, globals)
        const invocation = createInvocation(globalsWithInputs, hogFunction)
        invocation.id = invocationId.toString()

        const result = await this.hogExecutor.executeWithAsyncFunctions(invocation, { maxFetchRetries: 0 }) // Retries are handled by the batch export service

        // TODO: Follow up - we might want to more accuratelt link an execution to the fact it came from a batch export
        // We have the parent_id but that overrides the function id which is not always what we want
        // Likely after v0 we will want to add an extra field or concept depending on whether it is a backfill vs a standard run

        void this.promiseScheduler.schedule(
            Promise.all([
                this.invocationResultsService.queueInvocationResultsAndFlush([result]),
                this.hogWatcher.observeResultsBuffered(result),
            ])
        )

        return result
    }

    private buildRequestGlobals(
        event: RawClickHouseEvent,
        hogFunction: HogFunctionType,
        team: Team
    ): HogFunctionInvocationGlobals {
        const globals = convertToHogFunctionInvocationGlobals(event, team, this.siteUrl)
        const projectUrl = `${this.siteUrl}/project/${team.id}`

        return {
            ...globals,
            source: {
                name: hogFunction.name ?? `Hog function: ${hogFunction.id}`,
                url: `${projectUrl}/functions/${hogFunction.id}`,
            },
        }
    }

    public async stop(): Promise<void> {
        await this.promiseScheduler.waitForAllSettled()
    }
}

export class NotFoundError extends Error {
    constructor(message: string) {
        super(message)
        this.name = 'NotFoundError'
    }
}

export class ParseError extends Error {
    constructor(message: string) {
        super(message)
        this.name = 'ParseError'
    }
}
