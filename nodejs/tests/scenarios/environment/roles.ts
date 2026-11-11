import { z } from 'zod'

import { CdpRole } from '../cards'
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

export type Secrets = { encryptionSaltKeys: string; transactionalEmailJwtSecret: string }

export type RoleSpec = { role: Role; env: NodeJS.ProcessEnv }

export function secretsOf(env: NodeJS.ProcessEnv): Secrets {
    return {
        encryptionSaltKeys: env.ENCRYPTION_SALT_KEYS || '00beef0000beef0000beef0000beef00',
        transactionalEmailJwtSecret:
            env.WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_SECRET || 'local-dev-workflows-transactional-email-jwt',
    }
}

export function roleSpecs(base: NodeJS.ProcessEnv, edgeUrl: string, secrets: Secrets, stateDir: string): RoleSpec[] {
    const { AWS_PROFILE: _profile, ...inherited } = base
    return CdpRole.options.map((role) => ({
        role,
        env: {
            ...inherited,
            NODE_ENV: 'dev',
            PLUGIN_SERVER_MODE: role,
            HTTP_SERVER_PORT: String(ROLE_PORTS[role]),
            PGAPPNAME: `scenario-${role}`,
            SES_ENDPOINT: edgeUrl,
            SES_REGION: 'us-east-1',
            AWS_ACCESS_KEY_ID: 'scenario',
            AWS_SECRET_ACCESS_KEY: 'scenario',
            PERSONHOG_ENABLED: 'true',
            PERSONHOG_ADDR,
            ENCRYPTION_SALT_KEYS: secrets.encryptionSaltKeys,
            WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_SECRET: secrets.transactionalEmailJwtSecret,
            [MARKER_KEY]: stateDir,
        },
    }))
}
