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
import pg from 'pg'

import { listDestinationTypesHandler } from './destination-types/handlers'
import {
    createDestinationHandler,
    deleteDestinationHandler,
    getDestinationHandler,
    updateDestinationHandler,
} from './destinations/handlers'

const getApp = (config: NodeJS.ProcessEnv): Koa => {
    const app = new Koa()
    const router = new Router()

    assert(config.DATABASE_URL, 'DATABASE_URL environment variable must be set')

    const database = new pg.Client(config.CDP_DATABASE_URL)
    database.connect()

    router.get('/api/projects/:projectId/destination-types', listDestinationTypesHandler)
    router.post('/api/projects/:projectId/destinations', createDestinationHandler(database))
    router.get('/api/projects/:projectId/destinations/:destinationId', getDestinationHandler(database))
    router.put('/api/projects/:projectId/destinations/:destinationId', updateDestinationHandler(database))
    router.delete('/api/projects/:projectId/destinations/:destinationId', deleteDestinationHandler(database))

    app.use(bodyParser())
    app.use(router.routes())
    app.use(router.allowedMethods())

    return app
}

const config = {
    CDP_DATABASE_URL: 'postgres://posthog:posthog@localhost:5432/cdp',
    ...process.env,
}

const app = getApp(config)
app.listen(3000)
