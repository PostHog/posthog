/*

REST API for adding, updating, removing, and listing Destination. A Destination
represents a remote location that events should be sent to. The REST API tries
to be as simple as possible, and only supports JSON. It also tries to be of the
same response style as the API from the Django part of the application which
uses Django REST Framework. `Destination`s are stored in a separate logical
PostgreSQL database to the main application database to provide a clear
separation of concerns and limit the impact of e.g. heavy usage of the database
from the main application.

We also provide a read only DestinationType resource, which is used to list
the available DestinationTypes. This is used to retrieve the available
DestinationTypes for use as `Destination.type` as well as the schema for the 
`Destination.config` field. These types are defined in code for now, but it's 
possible that we will want to move them to the database in the future to allow
dynamic addition of new `DestinationType`s.

The implementation is based on Koajs, which is a popular Node.js web
application framework. Below we define the Koa application and the routes for
the REST API, using handlers defined in the `handlers.ts` files.

We do not at this point separate out the implementation
into Services, Repositories, and Controllers, but instead keep it all in one 
file, although that could be an improvement in the future if we find ourselves
using the destinations API in other parts of the CDP application.

*/

import assert from 'assert'
import Koa from 'koa'
import Router from 'koa-router'
import bodyParser from 'koa-bodyparser'
import logger from 'koa-pino-logger'
import pg from 'pg'
import jwt from 'koa-jwt'
import { NodeSDK } from '@opentelemetry/sdk-node'

import { ConsoleSpanExporter } from '@opentelemetry/sdk-trace-base'
import { PgInstrumentation } from '@opentelemetry/instrumentation-pg'
import { PinoInstrumentation } from '@opentelemetry/instrumentation-pino'

import { listDestinationTypesHandler } from './destination-types/handlers'
import {
    createDestinationHandler,
    deleteDestinationHandler,
    getDestinationHandler,
    updateDestinationHandler,
} from './destinations/handlers'

const getApp = async (config: NodeJS.ProcessEnv): Promise<Koa> => {
    const app = new Koa()
    const router = new Router()

    assert(config.DATABASE_URL, 'DATABASE_URL environment variable must be set')
    assert(config.SECRET_KEY, 'SECRET_KEY environment variable must be set')

    const database = new pg.Client({
        connectionString: config.DATABASE_URL,
        statement_timeout: 1000,
        connectionTimeoutMillis: 1000,
    })
    await database.connect()

    const opentelemetry = new NodeSDK({
        traceExporter: new ConsoleSpanExporter(),
        instrumentations: [new PgInstrumentation(), new PinoInstrumentation()],
    })
    opentelemetry.start()

    app.use(jwt({ secret: config.SECRET_KEY, key: 'jwtData' }))

    // For any route matching /api/projects/:projectId/... we want to make sure
    // that the JWT token contains the projectId as a claim. If it doesn't we
    // return a 403 Forbidden response.
    router.use('/api/projects/:projectId', async (ctx, next) => {
        const projectId = Number.parseInt(ctx.params.projectId)
        const jwtData = ctx.state.jwtData
        if (jwtData.projectIds.indexOf(projectId) === -1) {
            ctx.status = 403
            ctx.body = {
                detail: 'You do not have permission to perform this action.',
            }
            return
        }
        await next()
    })

    router.param('projectId', (projectId, ctx, next) => {
        if (projectId.match(/^[0-9]+$/)) {
            return next()
        }
        ctx.status = 400
        ctx.body = {
            detail: 'Invalid project ID.',
        }
    })

    router.get('/api/projects/:projectId/destination-types', listDestinationTypesHandler)
    router.post('/api/projects/:projectId/destinations', createDestinationHandler(database))
    router.get('/api/projects/:projectId/destinations/:destinationId', getDestinationHandler(database))
    router.put('/api/projects/:projectId/destinations/:destinationId', updateDestinationHandler(database))
    router.delete('/api/projects/:projectId/destinations/:destinationId', deleteDestinationHandler(database))

    app.use(logger())
    app.use(bodyParser())
    app.use(router.routes())
    app.use(router.allowedMethods())

    return app
}

const config = {
    DATABASE_URL: 'postgres://posthog:posthog@localhost:5432/cdp',
    SECRET_KEY: '<randomly generated secret key>',
    ...process.env,
}

getApp(config).then((app) => {
    app.listen(3000)
})
