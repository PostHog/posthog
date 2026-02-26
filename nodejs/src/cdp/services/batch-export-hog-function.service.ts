import { TeamManager } from '~/utils/team-manager'

import { RawClickHouseEvent, Team } from '../../types'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { UUID, UUIDT } from '../../utils/utils'
import { HogFunctionInvocationGlobals, HogFunctionType } from '../types'
import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '../types'
import { convertToHogFunctionInvocationGlobals } from '../utils'
import { createInvocation } from '../utils/invocation-utils'
import { HogExecutorService } from './hog-executor.service'
import { HogFunctionManagerService } from './managers/hog-function-manager.service'
import { HogFunctionMonitoringService } from './monitoring/hog-function-monitoring.service'
import { HogWatcherService } from './monitoring/hog-watcher.service'

export interface ExecutionRequest {
    batchExportId: string
    globals: HogFunctionInvocationGlobals
    hogFunction: HogFunctionType
    invocationId: UUID
    team: Team
}

export class BatchExportHogFunctionService {
    private promiseScheduler: PromiseScheduler

    constructor(
        private teamManager: TeamManager,
        private hogFunctionManager: HogFunctionManagerService,
        private hogExecutor: HogExecutorService,
        private hogWatcher: HogWatcherService,
        private hogFunctionMonitoringService: HogFunctionMonitoringService
    ) {
        this.promiseScheduler = new PromiseScheduler()
    }

    /**
     * Parses and validates all inputs required to execute a batch export hog function.
     * Returns a fully-typed HogFunctionExecutionRequest when successful, or throws
     * otherwise.
     *
     * @param params - Route parameters from the request
     * @param body - Request body containing the event and invocation ID
     * @param siteUrl - Required by convertToHogFunctionInvocationGlobals
     * @returns A validated batch export hog function execution request
     * @throws {ParseError} if any issues arise while parsing provided inputs
     * @throws {NotFoundError} if any required look-ups result in no findings
     */
    async parseRequest(
        params: { team_id: string; batch_export_id: string; hog_function_id: string },
        body: { clickhouse_event?: unknown; invocation_id?: unknown },
        siteUrl: string
    ): Promise<ExecutionRequest> {
        const invocationId = parseInvocationId(body.invocation_id)

        let team: Team | null
        try {
            team = await this.teamManager.getTeam(parseInt(params.team_id))
        } catch (e) {
            throw new ParseError('Invalid team_id: ' + params.team_id)
        }
        if (!team) {
            throw new NotFoundError('Missing team with id: ' + params.team_id)
        }

        let globals: HogFunctionInvocationGlobals
        try {
            globals = convertToHogFunctionInvocationGlobals(body.clickhouse_event as RawClickHouseEvent, team, siteUrl)
        } catch (e) {
            throw new ParseError('Invalid event')
        }
        if (!globals.event) {
            throw new ParseError('Empty event')
        }

        const hogFunction = await this.hogFunctionManager.getHogFunction(params.hog_function_id)
        if (!hogFunction) {
            throw new NotFoundError('Missing hog function with id: ' + params.hog_function_id)
        }
        if (hogFunction.team_id !== team.id || hogFunction.batch_export_id !== params.batch_export_id) {
            throw new NotFoundError('Missing hog function with id: ' + params.hog_function_id)
        }

        return {
            batchExportId: params.batch_export_id,
            globals,
            hogFunction,
            invocationId,
            team,
        }
    }

    /**
     * Handles a HogFunctionExecutionRequest by executing the associated hog function.
     *
     * @param request - The request to handle
     * @returns The result of the invocation
     */
    async handleRequest(
        request: ExecutionRequest
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
        const globalsWithInputs = await this.hogExecutor.buildInputsWithGlobals(request.hogFunction, request.globals)
        const invocation = createInvocation(globalsWithInputs, request.hogFunction)
        invocation.id = request.invocationId.toString()

        const result = await this.hogExecutor.executeWithAsyncFunctions(invocation)

        await this.hogFunctionMonitoringService.queueInvocationResults([result])
        void this.promiseScheduler.schedule(
            Promise.all([this.hogFunctionMonitoringService.flush(), this.hogWatcher.observeResultsBuffered(result)])
        )

        return result
    }

    public async stop(): Promise<void> {
        await this.promiseScheduler.waitForAllSettled()
    }
}

function parseInvocationId(raw: unknown): UUID {
    try {
        const uuid = typeof raw === 'string' ? new UUID(raw) : new UUIDT()
        return uuid
    } catch (e) {
        throw new ParseError('Invalid UUID: ' + raw)
    }
}

export class NotFoundError extends Error {
    constructor(message: string) {
        super(message)
        this.name = 'NotFoundError'
        Object.setPrototypeOf(this, NotFoundError.prototype)
    }
}

export class ParseError extends Error {
    constructor(message: string) {
        super(message)
        this.name = 'ParseError'
        Object.setPrototypeOf(this, ParseError.prototype)
    }
}
