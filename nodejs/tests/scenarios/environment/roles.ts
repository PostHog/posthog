import { z } from 'zod'

import { getDefaultCdpConfig } from '~/cdp/config'

import { CdpRole, Profile } from '../cards'
import { MARKER } from './processes'

export type Role = z.infer<typeof CdpRole>

export const ROLE_PORTS: Record<Role, number> = {
    'cdp-api': 6738,
    'cdp-processed-events': 6760,
    'cdp-cyclotron-worker-hogflow': 6761,
    'cdp-cyclotron-worker-email': 6762,
    'cdp-cyclotron-v2-janitor': 6763,
}

export const PERSONHOG_ADDR = '127.0.0.1:50052'

export type Secrets = { encryptionSaltKeys: string; transactionalEmailJwtSecret: string }

export type RoleSpec = { role: Role; env: NodeJS.ProcessEnv }

export type ConsumerGroup = { group: string; topics: string[] }

const ROLE_CONSUMERS: Partial<Record<Role, (env: NodeJS.ProcessEnv) => ConsumerGroup>> = {
    'cdp-processed-events': (env) => {
        const defaults = getDefaultCdpConfig()
        return {
            group: env.CDP_EVENTS_CONSUMER_GROUP_ID || defaults.CDP_EVENTS_CONSUMER_GROUP_ID,
            topics: [env.CDP_EVENTS_CONSUMER_TOPIC || defaults.CDP_EVENTS_CONSUMER_TOPIC],
        }
    },
}

export function secretsOf(env: NodeJS.ProcessEnv): Secrets {
    return {
        encryptionSaltKeys: env.ENCRYPTION_SALT_KEYS || '00beef0000beef0000beef0000beef00',
        transactionalEmailJwtSecret:
            env.WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_SECRET || 'local-dev-workflows-transactional-email-jwt',
    }
}

export function roleSpecs(
    base: NodeJS.ProcessEnv,
    edgeUrl: string,
    secrets: Secrets,
    settings: Profile['settings'] = {}
): RoleSpec[] {
    const { AWS_PROFILE: _profile, ...inherited } = base
    const [markerKey, markerValue] = MARKER.split('=')
    return CdpRole.options.map((role) => ({
        role,
        env: {
            ...inherited,
            NODE_ENV: 'dev',
            SES_ENDPOINT: edgeUrl,
            SES_REGION: 'us-east-1',
            AWS_ACCESS_KEY_ID: 'scenario',
            AWS_SECRET_ACCESS_KEY: 'scenario',
            PERSONHOG_ENABLED: 'true',
            PERSONHOG_ADDR,
            ENCRYPTION_SALT_KEYS: secrets.encryptionSaltKeys,
            WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_SECRET: secrets.transactionalEmailJwtSecret,
            ...settings,
            PLUGIN_SERVER_MODE: role,
            HTTP_SERVER_PORT: String(ROLE_PORTS[role]),
            PGAPPNAME: `scenario-${role}`,
            [markerKey]: markerValue,
        },
    }))
}

export function consumerGroupsOf(specs: RoleSpec[]): ConsumerGroup[] {
    return specs.flatMap((spec) => ROLE_CONSUMERS[spec.role]?.(spec.env) ?? [])
}
