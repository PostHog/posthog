import { getRegionForHost } from 'lib/oauth/oauthClient'

import { PreflightStatus, Realm } from '~/types'

/**
 * `/_preflight/` answers only same-origin requests, so an app embedded on another origin cannot fetch it.
 * The embed talks to one known backend, so it states that backend's preflight instead. The service
 * checks report healthy because the embed has no way to see them, and the capability flags take the
 * conservative value where a wrong guess would offer a setup flow the backend cannot finish.
 */
export function buildEmbeddedPreflight(backendHost: string): PreflightStatus {
    const region = getRegionForHost(backendHost)
    const cloud = region !== null
    return {
        django: true,
        plugins: true,
        redis: true,
        db: true,
        clickhouse: true,
        kafka: true,
        celery: true,
        object_storage: true,
        initiated: true,
        can_create_org: cloud,
        cloud,
        demo: false,
        realm: cloud ? Realm.Cloud : Realm.SelfHostedClickHouse,
        region,
        available_social_auth_providers: {},
        email_service_available: cloud,
        slack_service: { available: false },
        data_warehouse_integrations: { hubspot: {}, salesforce: {} },
        wizard_cloud_run_available: false,
        site_url: backendHost,
    }
}
