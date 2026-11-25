import { z } from 'zod'

import { getDefaultCdpConfig } from '~/cdp/config'
import { PluginServerMode } from '~/common/config'
import { overrideConfigWithEnv } from '~/common/config/config'

import { CdpRole, Profile } from '../cards'
import { ReplicaOf } from './identity'
import { MARKER_KEY } from './processes'

export type Role = z.infer<typeof CdpRole>

export const ROLE_PORTS: Record<Role, number> = {
    'cdp-api': 6738,
    'cdp-processed-events': 6760,
    'cdp-cyclotron-worker-hogflow': 6761,
    'cdp-cyclotron-worker-email': 6762,
    'cdp-cyclotron-v2-janitor': 6763,
    'cdp-ses-webhooks': 6764,
    'cdp-intake-transactional-email': 6765,
    'cdp-intake-workflow-webhook': 6766,
}

export const MODES_WITHOUT_A_ROLE: Partial<Record<PluginServerMode, string>> = {
    [PluginServerMode.cdp_person_updates]: 'no card triggers a workflow on a person update',
    [PluginServerMode.cdp_data_warehouse_events]: 'no card triggers a workflow on a data warehouse row',
    [PluginServerMode.cdp_internal_events]: 'no card triggers a workflow on an internal event',
    [PluginServerMode.cdp_cyclotron_worker]: 'it runs destinations, and the cards drive workflows',
    [PluginServerMode.cdp_precalculated_filters]: 'the mode boots with no capabilities',
    [PluginServerMode.cdp_hogflow_subscription_matcher]: 'no card triggers a workflow on a subscription',
    [PluginServerMode.cdp_cohort_membership]: 'no card triggers a workflow on cohort membership',
    [PluginServerMode.cdp_cohort_membership_triggers]: 'no card triggers a workflow on cohort membership',
    [PluginServerMode.cdp_cyclotron_worker_email_sandbox]: 'the cards send through the email worker, not the sandbox',
    [PluginServerMode.cdp_legacy_on_event]: 'no card runs a legacy destination',
    [PluginServerMode.cdp_cyclotron_worker_batch_resolve]: 'no card runs a batch workflow',
    [PluginServerMode.cdp_rerun_worker]: 'an operator runs it to rerun failed runs, and no card reruns',
    [PluginServerMode.cdp_dlq_replay]: 'an operator runs it to drain the events dead-letter topic',
    [PluginServerMode.cdp_hogflow_scheduler]: 'no card runs a scheduled workflow',
}

export const SES_WEBHOOKS_GROUP = 'cdp-ses-webhooks-consumer'

export const INTAKE_TRANSACTIONAL_EMAIL_GROUP = 'cdp-intake-transactional-email-consumer'

export const INTAKE_WORKFLOW_WEBHOOK_GROUP = 'cdp-intake-workflow-webhook-consumer'
export const INTAKE_GROUPS: readonly string[] = [INTAKE_TRANSACTIONAL_EMAIL_GROUP, INTAKE_WORKFLOW_WEBHOOK_GROUP]

const INTAKE_ROLES: readonly Role[] = ['cdp-intake-transactional-email', 'cdp-intake-workflow-webhook']

const isIntake = (role: Role): boolean => INTAKE_ROLES.includes(role)

export const PERSONHOG_ADDR = '127.0.0.1:50052'

export const SES_RATE_LIMITER_VALKEY = { host: '127.0.0.1', port: 6390 }

export const SCENARIO_SESSION_PREFIX = 'scenario-'

export type Secrets = { encryptionSaltKeys: string; transactionalEmailJwtSecret: string }

export type Replicas = Profile['replicas']

export type RoleId = ReplicaOf<Role>

export type RoleSpec = RoleId & { port: number; env: NodeJS.ProcessEnv }

const REPLICA_PORT_OFFSET = 100

export const portOf = ({ role, replica }: RoleId): number => ROLE_PORTS[role] + REPLICA_PORT_OFFSET * replica

export const roleIdsOf = (replicas: Replicas = {}): RoleId[] =>
    CdpRole.options.flatMap((role) => Array.from({ length: replicas[role] ?? 1 }, (_, replica) => ({ role, replica })))

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
    sesValkey: { host: string; port: number } = SES_RATE_LIMITER_VALKEY,
    replicas: Replicas = {}
): RoleSpec[] {
    const {
        AWS_PROFILE: _profile,
        SCENARIO_POOLER_URLS: poolerUrls,
        CDP_RATE_LIMITER_REFILL_RATE: _refillRate,
        CDP_SES_RATE_LIMIT_REFILL_PER_SECOND: _sesRefill,
        CDP_SES_RATE_LIMIT_CAPACITY: _sesCapacity,
        CONSUMER_BATCH_SIZE: _batchSize,
        CDP_INTAKE_DLQ_DRAIN: _drain,
        CDP_INTAKE_TRANSACTIONAL_EMAIL_TOPIC: _emailTopic,
        CDP_INTAKE_WORKFLOW_WEBHOOK_TOPIC: _webhookTopic,
        ...inherited
    } = base
    const poolers = poolerUrls ? poolerUrls.split(',') : []
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
        CDP_INTAKE_KAFKA_ASYNC_TEAMS: '*',
        CDP_SEAL_TRANSACTIONAL_EMAIL_STATE: 'true',
        ...settings,
    }
    return roleIdsOf(replicas).map((id, index) => ({
        ...id,
        port: portOf(id),
        env: {
            ...(isIntake(id.role) ? { CDP_DLQ_ENABLED: 'true' } : {}),
            ...configured,
            ...(poolers.length > 0 ? { CYCLOTRON_NODE_DATABASE_URL: poolers[index % poolers.length] } : {}),
            SES_ENDPOINT: edge.url,
            HTTPS_PROXY: edge.url,
            ...(edge.caCertPath ? { NODE_EXTRA_CA_CERTS: edge.caCertPath } : {}),
            PERSONHOG_ADDR,
            SES_RATE_LIMITER_VALKEY_HOST: sesValkey.host,
            SES_RATE_LIMITER_VALKEY_PORT: String(sesValkey.port),
            ENCRYPTION_SALT_KEYS: secrets.encryptionSaltKeys,
            WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_SECRET: secrets.transactionalEmailJwtSecret,
            PLUGIN_SERVER_MODE: id.role,
            HTTP_SERVER_PORT: String(portOf(id)),
            PGAPPNAME: `${SCENARIO_SESSION_PREFIX}${id.role}`,
            KAFKA_CONSUMER_CLIENT_ID: `${SCENARIO_SESSION_PREFIX}${id.role}`,
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
    return specs.flatMap(({ role, replica, env }): ConsumerGroup[] => {
        if (replica !== 0) {
            return []
        }
        switch (role) {
            case 'cdp-processed-events':
                return [
                    {
                        group: env.CDP_EVENTS_CONSUMER_GROUP_ID || defaults.CDP_EVENTS_CONSUMER_GROUP_ID,
                        topics: [env.CDP_EVENTS_CONSUMER_TOPIC || `${env.KAFKA_PREFIX || ''}clickhouse_events_json`],
                    },
                ]
            case 'cdp-ses-webhooks':
                return [
                    {
                        group: SES_WEBHOOKS_GROUP,
                        topics: [env.CDP_SES_WEBHOOKS_TOPIC || `${env.KAFKA_PREFIX || ''}cdp_ses_webhooks`],
                    },
                ]
            case 'cdp-intake-transactional-email':
                return [
                    {
                        group: INTAKE_TRANSACTIONAL_EMAIL_GROUP,
                        topics: [
                            env.CDP_INTAKE_TRANSACTIONAL_EMAIL_TOPIC ||
                                `${env.KAFKA_PREFIX || ''}cdp_intake_transactional_email`,
                        ],
                    },
                ]
            case 'cdp-intake-workflow-webhook':
                return [
                    {
                        group: INTAKE_WORKFLOW_WEBHOOK_GROUP,
                        topics: [
                            env.CDP_INTAKE_WORKFLOW_WEBHOOK_TOPIC ||
                                `${env.KAFKA_PREFIX || ''}cdp_intake_workflow_webhook`,
                        ],
                    },
                ]
            default:
                return []
        }
    })
}

export function intakeTopicsOf(specs: RoleSpec[]): string[] {
    const intake = specs.filter(({ role }) => isIntake(role))
    const topics = [
        ...consumerGroupsOf(intake).flatMap(({ topics }) => topics),
        ...intake.map(({ env }) => env.CDP_INTAKE_DLQ_TOPIC || `${env.KAFKA_PREFIX || ''}cdp_intake_dlq`),
    ]
    return [...new Set(topics)]
}
