import { convertJSToHog } from '@posthog/hogvm'
import express from 'express'
import { DateTime } from 'luxon'

import { Hub } from '../types'
import { status } from '../utils/status'
import { delay } from '../utils/utils'
import { AsyncFunctionExecutor } from './async-function-executor'
import { HogExecutor } from './hog-executor'
import { HogFunctionManager } from './hog-function-manager'
import { HogWatcher, HogWatcherState } from './hog-watcher'
import { HogFunctionInvocation, HogFunctionInvocationAsyncRequest, HogFunctionType, LogEntry } from './types'

export class CdpApi {
    private hogExecutor: HogExecutor
    private hogFunctionManager: HogFunctionManager
    private asyncFunctionExecutor: AsyncFunctionExecutor
    private hogWatcher: HogWatcher

    constructor(
        private hub: Hub,
        dependencies: {
            hogExecutor: HogExecutor
            hogFunctionManager: HogFunctionManager
            asyncFunctionExecutor: AsyncFunctionExecutor
            hogWatcher: HogWatcher
        }
    ) {
        this.hogExecutor = dependencies.hogExecutor
        this.hogFunctionManager = dependencies.hogFunctionManager
        this.asyncFunctionExecutor = dependencies.asyncFunctionExecutor
        this.hogWatcher = dependencies.hogWatcher
    }

    router(): express.Router {
        const router = express.Router()

        const asyncHandler =
            (fn: (req: express.Request, res: express.Response) => Promise<void>) =>
            (req: express.Request, res: express.Response, next: express.NextFunction): Promise<void> =>
                fn(req, res).catch(next)

        router.post('/api/projects/:team_id/hog_functions/:id/invocations', asyncHandler(this.postFunctionInvocation))
        router.get('/api/projects/:team_id/hog_functions/:id/status', asyncHandler(this.getFunctionStatus()))
        router.patch('/api/projects/:team_id/hog_functions/:id/status', asyncHandler(this.patchFunctionStatus()))

        return router
    }

    private getFunctionStatus =
        () =>
        async (req: express.Request, res: express.Response): Promise<void> => {
            const { id } = req.params
            const summary = await this.hogWatcher.getState(id)

            res.json(summary)
        }

    private patchFunctionStatus =
        () =>
        async (req: express.Request, res: express.Response): Promise<void> => {
            const { id } = req.params
            const { state } = req.body

            // Check that state is valid
            if (!Object.values(HogWatcherState).includes(state)) {
                res.status(400).json({ error: 'Invalid state' })
                return
            }

            const summary = await this.hogWatcher.getState(id)

            // Only allow patching the status if it is different from the current status

            if (summary.state !== state) {
                await this.hogWatcher.forceStateChange(id, state)
            }

            // Hacky - wait for a little to give a chance for the state to change
            await delay(100)

            res.json(await this.hogWatcher.getState(id))
        }

    private postFunctionInvocation = async (req: express.Request, res: express.Response): Promise<void> => {
        try {
            const { id, team_id } = req.params
            const { globals, mock_async_functions, configuration } = req.body

            status.info('⚡️', 'Received invocation', { id, team_id, body: req.body })

            if (!globals) {
                res.status(400).json({ error: 'Missing event' })
                return
            }

            const [hogFunction, team] = await Promise.all([
                this.hogFunctionManager.fetchHogFunction(req.params.id),
                this.hub.teamManager.fetchTeam(parseInt(team_id)),
            ]).catch(() => {
                return [null, null]
            })
            if (!hogFunction || !team || hogFunction.team_id !== team.id) {
                res.status(404).json({ error: 'Hog function not found' })
                return
            }

            const invocation: HogFunctionInvocation = {
                id,
                globals: globals,
                teamId: team.id,
                hogFunctionId: id,
                timings: [],
            }

            // We use the provided config if given, otherwise the function's config
            // We use the provided config if given, otherwise the function's config
            const compoundConfiguration: HogFunctionType = {
                ...hogFunction,
                ...(configuration ?? {}),
            }

            // TODO: Type the configuration better so we don't make mistakes here
            await this.hogFunctionManager.enrichWithIntegrations([compoundConfiguration])

            let response = this.hogExecutor.execute(compoundConfiguration, invocation)
            const logs: LogEntry[] = []

            while (response.asyncFunctionRequest) {
                invocation.vmState = response.invocation.vmState

                const asyncFunctionRequest = response.asyncFunctionRequest

                if (mock_async_functions || asyncFunctionRequest.name !== 'fetch') {
                    response.logs.push({
                        level: 'info',
                        timestamp: DateTime.now(),
                        message: `Async function '${asyncFunctionRequest.name}' was mocked with arguments:`,
                    })

                    response.logs.push({
                        level: 'info',
                        timestamp: DateTime.now(),
                        message: `${asyncFunctionRequest.name}(${asyncFunctionRequest.args
                            .map((x) => JSON.stringify(x, null, 2))
                            .join(', ')})`,
                    })

                    // Add the state, simulating what executeAsyncResponse would do
                    invocation.vmState!.stack.push(convertJSToHog({ status: 200, body: {} }))
                } else {
                    const asyncInvocationRequest: HogFunctionInvocationAsyncRequest = {
                        state: '', // WE don't care about the state for this level of testing
                        teamId: team.id,
                        hogFunctionId: hogFunction.id,
                        asyncFunctionRequest,
                    }
                    const asyncRes = await this.asyncFunctionExecutor!.execute(asyncInvocationRequest, {
                        sync: true,
                    })

                    if (!asyncRes || asyncRes.asyncFunctionResponse.error) {
                        response.logs.push({
                            level: 'error',
                            timestamp: DateTime.now(),
                            message: 'Failed to execute async function',
                        })
                    }
                    invocation.vmState!.stack.push(convertJSToHog(asyncRes?.asyncFunctionResponse.response ?? null))
                }

                logs.push(...response.logs)
                response = this.hogExecutor.execute(compoundConfiguration, invocation)
            }

            logs.push(...response.logs)

            res.json({
                status: response.finished ? 'success' : 'error',
                error: String(response.error),
                logs: logs,
            })
        } catch (e) {
            console.error(e)
            res.status(500).json({ error: e.message })
        }
    }
}
