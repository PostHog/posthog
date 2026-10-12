/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface OpenFgaStatusApi {
    /** Whether the OpenFGA server answered every status request. */
    reachable: boolean
    /** OpenFGA API URL that the client uses, without any user name or password. */
    api_url: string
    /**
     * Name of the OpenFGA store. Null when no store was found or OpenFGA failed.
     * @nullable
     */
    store_name: string | null
    /**
     * ID of the OpenFGA store. Null when no store was found or OpenFGA failed.
     * @nullable
     */
    store_id: string | null
    /**
     * ID of the latest authorization model in the store. Null when the store has no model or OpenFGA failed.
     * @nullable
     */
    authorization_model_id: string | null
    /**
     * Class name of the error that made OpenFGA unreachable. Null when it is reachable.
     * @nullable
     */
    error: string | null
}
