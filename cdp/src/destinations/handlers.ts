/*
 *
 * This file is responsible for handling the destination API. It provides
 * handlers for creating, updating, and deleting destinations, as well as
 * listing destinations.
 *
 * Note that we do not delete destinations, but instead mark them as deleted. This
 * is to ensure that we can keep a history of destinations that have been used
 * in the past.
 *
 */

import { randomUUID } from 'crypto'
import Koa from 'koa'
import pg from 'pg'
import Ajv, { JSONSchemaType } from 'ajv'
import { SQL } from '../sql-template-string'
import { listDestinationTypes } from '../destination-types/handlers'

type DestinationData = {
    name: string // Name displayed to the user
    description: string // Description displayed to the user
    type: string // Type of destination, e.g. webhook, email, Stripe etc.
    config: Record<string, unknown> // Configuration for the destination, e.g. webhook URL, email address, Stripe API key etc.
}

type DestinationCreateRequest = DestinationData

const ajv = new Ajv()

const createDestinationRequestSchema: JSONSchemaType<DestinationCreateRequest> = {
    type: 'object',
    properties: {
        name: {
            type: 'string',
            description: 'Name displayed to the user',
        },
        description: {
            type: 'string',
            description: 'Description displayed to the user',
        },
        type: {
            type: 'string',
            description: 'Type of destination, e.g. webhook, email, Stripe etc.',
        },
        config: {
            type: 'object',
            description: 'Configuration for the destination, e.g. webhook URL, email address, Stripe API key etc.',
        },
    },
    required: ['name', 'description', 'type', 'config'],
}

const createDestinationRequestValidator = ajv.compile(createDestinationRequestSchema)

export const createDestinationHandler =
    (database: pg.Client) =>
    async (ctx: Koa.Context): Promise<void> => {
        const destination = ctx.request.body
        // Validate the request body using Ajv
        const requestValid = createDestinationRequestValidator(destination)
        if (!requestValid) {
            ctx.status = 400
            ctx.body = createDestinationRequestValidator.errors
            return
        }

        // Validate the config against the destination type schema
        const config = destination.config
        const destinationType = (await listDestinationTypes()).find(
            (destinationType) => destinationType.type === destination.type
        )
        // If the destination type doesn't exist, return a 400
        if (!destinationType) {
            ctx.status = 400
            return
        }

        // If the config doesn't match the schema, return a 400. We use AJV to
        // perform validation.
        const typeValidator = ajv.compile(destinationType.configSchema)
        const typeValid = typeValidator(config)
        if (!typeValid) {
            ctx.status = 400
            ctx.body = typeValidator.errors
            return
        }

        const id = randomUUID()
        const result = await database.query(
            SQL`
                INSERT INTO destinations (
                    id, 
                    team_id,
                    name, 
                    description, 
                    type, 
                    config,
                    created_by_id
                ) VALUES (
                    ${id}, 
                    ${ctx.params.projectId},
                    ${destination.name}, 
                    ${destination.description}, 
                    ${destination.type}, 
                    ${destination.config},
                    ${ctx.state.jwtData.userId}
                ) RETURNING *
            `
        )

        ctx.status = 201
        ctx.body = result.rows[0]
    }

export const getDestinationHandler =
    (database: pg.Client) =>
    async (ctx: Koa.Context): Promise<void> => {
        const id = ctx.params.destinationId
        // Validate id is a uuid
        if (!id.match(/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i)) {
            ctx.status = 400
            return
        }

        const result = await database.query(
            SQL`
                SELECT * 
                FROM destinations 
                WHERE 
                    id = ${id} AND 
                    team_id = ${ctx.params.projectId} AND
                    is_deleted = false
            `
        )

        if (result.rowCount === 0) {
            ctx.status = 404
            return
        }

        ctx.status = 200
        ctx.body = result.rows[0]
    }

type DestinationUpdateRequest = DestinationData

const updateDestinationRequestSchema: JSONSchemaType<DestinationUpdateRequest> = createDestinationRequestSchema

const updateDestinationRequestValidator = ajv.compile(updateDestinationRequestSchema)

export const updateDestinationHandler =
    (database: pg.Client) =>
    async (ctx: Koa.Context): Promise<void> => {
        const destination = ctx.request.body
        // Validate the request body using Ajv
        const requestValid = updateDestinationRequestValidator(destination)
        if (!requestValid) {
            ctx.status = 400
            ctx.body = updateDestinationRequestValidator.errors
            return
        }

        const id = ctx.params.destinationId
        // Validate id is a uuid
        if (!id.match(/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i)) {
            ctx.status = 400
            return
        }

        // Validate the config against the destination type schema
        const config = destination.config
        const destinationType = (await listDestinationTypes()).find(
            (destinationType) => destinationType.type === destination.type
        )
        // If the destination type doesn't exist, return a 400
        if (!destinationType) {
            ctx.status = 400
            return
        }

        // If the config doesn't match the schema, return a 400. We use AJV to
        // perform validation.
        const typeValidator = ajv.compile(destinationType.configSchema)
        const typeValid = typeValidator(config)
        if (!typeValid) {
            ctx.status = 400
            ctx.body = typeValidator.errors
            return
        }

        // NOTE: you cannot update a deleted destination. In the case that you
        // try to update a deleted destination, we will return a 404. This is
        // detected by the update row count being 0.
        const result = await database.query(
            SQL`
                UPDATE destinations 
                SET 
                    name = ${destination.name}, 
                    description = ${destination.description}, 
                    type = ${destination.type}, 
                    config = ${destination.config} 
                WHERE 
                    id = ${id} AND 
                    team_id = ${ctx.params.projectId} AND
                    is_deleted = false 
                RETURNING *
            `
        )

        if (result.rowCount === 0) {
            ctx.status = 404
            return
        }

        ctx.status = 200
        ctx.body = result.rows[0]
    }

export const deleteDestinationHandler =
    (database: pg.Client) =>
    async (ctx: Koa.Context): Promise<void> => {
        // NOTE: we do not delete the destination, but instead mark it as deleted
        const id = ctx.params.destinationId
        // Validate id is a uuid
        if (!id.match(/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i)) {
            ctx.status = 400
            return
        }

        const result = await database.query(SQL`
            UPDATE destinations
            SET is_deleted = true 
            WHERE 
                id = ${id} AND
                team_id = ${ctx.params.projectId}
        `)

        if (result.rowCount === 0) {
            ctx.status = 404
            return
        }

        ctx.status = 204
    }
