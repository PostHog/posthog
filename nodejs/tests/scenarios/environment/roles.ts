import { z } from 'zod'

import { getDefaultCdpConfig } from '~/cdp/config'
import { overrideConfigWithEnv } from '~/common/config/config'

import { CdpRole, Profile } from '../cards'
import { MARKER_KEY } from './processes'

export type Role = z.infer<typeof CdpRole>

export const ROLE_PORTS: Record<Role, number> = {
    'cdp-api': 6738,
    'cdp-processed-events': 6760,
    'cdp-cyclotron-worker-hogflow': 6761,
    'cdp-cyclotron-worker-email': 6762,
    'cdp-cyclotron-v2-janitor': 6763,
}

export const PERSONHOG_ADDR = '127.0.0.1:50052'

export const SES_RATE_LIMITER_VALKEY = { host: '127.0.0.1', port: 6390 }

export type Secrets = { encryptionSaltKeys: string; transactionalEmailJwtSecret: string }

export type RoleSpec = { role: Role; env: NodeJS.ProcessEnv }

export type EdgeAddress = { url: string; caCertPath?: string }

export type ConsumerGroup = { group: string; topics: string[] }

export function secretsOf(env: NodeJS.ProcessEnv): Secrets {
    return {
        encryptionSaltKeys: env.ENCRYPTION_SALT_KEYS || '00beef0000beef0000beef0000beef00',
        transactionalEmailJwtSecret:
            env.WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_SECRET || 'local-dev-workflows-transactional-email-jwt',
    }
}

export function roleSpecs(
    base: NodeJS.ProcessEnv,
    edge: EdgeAddress,
    secrets: Secrets,
    stateDir: string,
    settings: Profile['settings'] = {},
    sesValkey: { host: string; port: number } = SES_RATE_LIMITER_VALKEY
): RoleSpec[] {
    const { AWS_PROFILE: _profile, ...inherited } = base
    const {
        KAFKA_CONSUMER_GROUP_ID: _group,
        EXTERNAL_REQUEST_PROXY_TEAMS: _proxyTeams,
        ...configured
    }: NodeJS.ProcessEnv = {
        ...inherited,
        NODE_ENV: 'dev',
        SES_REGION: 'us-east-1',
        AWS_ACCESS_KEY_ID: 'scenario',
        AWS_SECRET_ACCESS_KEY: 'scenario',
        PERSONHOG_ENABLED: 'true',
        ...settings,
    }
    return CdpRole.options.map((role) => ({
        role,
        env: {
            ...configured,
            SES_ENDPOINT: edge.url,
            HTTPS_PROXY: edge.url,
            ...(edge.caCertPath ? { NODE_EXTRA_CA_CERTS: edge.caCertPath } : {}),
            PERSONHOG_ADDR,
            SES_RATE_LIMITER_VALKEY_HOST: sesValkey.host,
            SES_RATE_LIMITER_VALKEY_PORT: String(sesValkey.port),
            ENCRYPTION_SALT_KEYS: secrets.encryptionSaltKeys,
            WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_SECRET: secrets.transactionalEmailJwtSecret,
            PLUGIN_SERVER_MODE: role,
            HTTP_SERVER_PORT: String(ROLE_PORTS[role]),
            PGAPPNAME: `scenario-${role}`,
            [MARKER_KEY]: stateDir,
        },
    }))
}

export function fetchRetriesOf({ env }: RoleSpec): number {
    const retries = overrideConfigWithEnv(getDefaultCdpConfig(), env).CDP_FETCH_RETRIES
    if (!Number.isFinite(retries)) {
        throw new Error(`CDP_FETCH_RETRIES ${env.CDP_FETCH_RETRIES} is not a number of retries`)
    }
    return retries
}

export function consumerGroupsOf(specs: RoleSpec[]): ConsumerGroup[] {
    const defaults = getDefaultCdpConfig()
    return specs
        .filter(({ role }) => role === 'cdp-processed-events')
        .map(({ env }) => ({
            group: env.CDP_EVENTS_CONSUMER_GROUP_ID || defaults.CDP_EVENTS_CONSUMER_GROUP_ID,
            topics: [env.CDP_EVENTS_CONSUMER_TOPIC || `${env.KAFKA_PREFIX || ''}clickhouse_events_json`],
        }))
}
