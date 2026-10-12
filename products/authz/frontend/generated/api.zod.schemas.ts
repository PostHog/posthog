/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const OpenFgaStatusApi = zod.object({
    reachable: zod.boolean().describe('Whether the OpenFGA server answered every status request.'),
    api_url: zod.string().describe('OpenFGA API URL that the client uses, without any user name or password.'),
    store_name: zod
        .string()
        .nullable()
        .describe('Name of the OpenFGA store. Null when no store was found or OpenFGA failed.'),
    store_id: zod
        .string()
        .nullable()
        .describe('ID of the OpenFGA store. Null when no store was found or OpenFGA failed.'),
    authorization_model_id: zod
        .string()
        .nullable()
        .describe(
            'ID of the latest authorization model in the store. Null when the store has no model or OpenFGA failed.'
        ),
    error: zod
        .string()
        .nullable()
        .describe('Class name of the error that made OpenFGA unreachable. Null when it is reachable.'),
})

export type OpenFgaStatusApi = zod.input<typeof OpenFgaStatusApi>
export type OpenFgaStatusApiOutput = zod.output<typeof OpenFgaStatusApi>
