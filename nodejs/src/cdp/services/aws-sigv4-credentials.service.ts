import { AssumeRoleCommand, AssumeRoleCommandOutput, STSClient, STSServiceException } from '@aws-sdk/client-sts'
import { NodeHttpHandler } from '@smithy/node-http-handler'
import { Counter } from 'prom-client'

import { logger } from '~/common/utils/logger'
import { PubSub } from '~/common/utils/pubsub'
import { TeamManager } from '~/common/utils/team-manager'

import { CyclotronInvocationQueueParametersFetchAwsSigV4Type } from '../schema/cyclotron'
import { HogFunctionType, IntegrationType } from '../types'
import { ResolvedAwsSigV4Credentials, resolveAwsSigV4Credentials } from '../utils/aws-sigv4'
import { resolveHogFunctionInputValue } from '../utils/hog-function-inputs'
import { IntegrationManagerService } from './managers/integration-manager.service'

// Role chaining limits a session to one hour, and the session for the customer's role is always chained.
const SESSION_DURATION_SECONDS = 3600
// Refresh long before expiry, so that a slow STS call does not leave requests without credentials.
const REFRESH_BEFORE_EXPIRY_MS = 10 * 60 * 1000
// AWS checks the session when it receives the request, so credentials this close to expiry are not used.
const MIN_REMAINING_VALIDITY_MS = 60 * 1000
// Every invocation of a broken connection would otherwise call STS twice, and all connections share
// the STS quota of PostHog's role. A failure that can pass, such as throttling, waits less.
const FAILURE_RETRY_DELAY_MS = 60 * 1000
const TRANSIENT_FAILURE_RETRY_DELAY_MS = 10 * 1000
const STS_CONNECTION_TIMEOUT_MS = 2000
const STS_REQUEST_TIMEOUT_MS = 5000
// Lookups for a connection wait on its pending assume, so an assume must always end.
const ASSUME_DEADLINE_MS = 10 * 1000
const STS_THROTTLING_ERRORS = new Set(['Throttling', 'ThrottlingException', 'RequestLimitExceeded'])

// A connection signs only requests to the endpoint of its own service. Hog code chooses the URL, so without
// this check it could sign any AWS API call, such as an STS call that returns credentials in the response.
// The customer's role can grant more than `sessionActions`, but the PostHog session for that role only gets
// these actions. Streams that use a customer managed KMS key need kms:GenerateDataKey for every write.
const CONNECTION_KINDS: Partial<Record<IntegrationType['kind'], { service: string; sessionActions: string[] }>> = {
    'aws-kinesis': {
        service: 'kinesis',
        sessionActions: ['kinesis:PutRecord', 'kinesis:PutRecords', 'kms:GenerateDataKey'],
    },
}

const AWS_REGION_RE = /^[a-z]{2}(-[a-z]+)+-\d+$/

const defaultServiceOrigin = (service: string, region: string): string => `https://${service}.${region}.amazonaws.com`

const awsRoleCredentialsCounter = new Counter({
    name: 'cdp_aws_role_credentials_total',
    help: 'Credential lookups for AWS connections that assume a customer IAM role, by result',
    labelNames: ['result'] as const,
})

type TemporaryCredentials = {
    accessKeyId: string
    secretAccessKey: string
    sessionToken: string
    expiresAt: number
}

type RoleSession = {
    roleArn: string
    credentials?: TemporaryCredentials
    pendingAssume?: Promise<void>
    failure?: { error: string; retryAt: number; transient: boolean }
}

type RoleRequest = {
    integrationId: number
    teamId: number
    roleArn: string
    externalId: string
    sessionActions: string[]
}

export type StsClientLike = {
    send(command: AssumeRoleCommand, options?: { abortSignal?: AbortSignal }): Promise<AssumeRoleCommandOutput>
    destroy(): void
}

export type AwsSigV4CredentialsConfig = {
    externalRoleArn: string
    stsRegion: string
}

export type AwsSigV4CredentialsDependencies = {
    integrationManager: Pick<IntegrationManagerService, 'get'>
    teamManager: Pick<TeamManager, 'getTeam'>
    pubSub: Pick<PubSub, 'on'>
    createStsClient?: (credentials?: TemporaryCredentials) => StsClientLike
    serviceOrigin?: (service: string, region: string) => string
}

class AwsRoleAssumeError extends Error {
    constructor(
        message: string,
        readonly transient: boolean
    ) {
        super(message)
    }
}

// Network errors and timeouts never get an answer from STS, so they can pass too.
const isTransientStsError = (error: unknown): boolean =>
    !(error instanceof STSServiceException) || error.$fault === 'server' || STS_THROTTLING_ERRORS.has(error.name)

const failed = (error: string): ResolvedAwsSigV4Credentials => ({
    ok: false,
    error: `AWS SigV4 signing failed: ${error}`,
})

const isUsable = (
    credentials: TemporaryCredentials | undefined,
    marginMs: number
): credentials is TemporaryCredentials => !!credentials && credentials.expiresAt - Date.now() > marginMs

const sessionPolicy = (actions: string | string[], resource: string): string =>
    JSON.stringify({ Version: '2012-10-17', Statement: [{ Effect: 'Allow', Action: actions, Resource: resource }] })

function toTemporaryCredentials(response: AssumeRoleCommandOutput): TemporaryCredentials {
    const { AccessKeyId, SecretAccessKey, SessionToken, Expiration } = response.Credentials ?? {}
    if (!AccessKeyId || !SecretAccessKey || !SessionToken || !Expiration) {
        throw new Error('STS returned no credentials')
    }
    return {
        accessKeyId: AccessKeyId,
        secretAccessKey: SecretAccessKey,
        sessionToken: SessionToken,
        expiresAt: Expiration.getTime(),
    }
}

/**
 * Resolves the credentials that sign an `aws_sigv4` fetch.
 *
 * When `integration_input` is unset or its input is empty, the credentials come from the key inputs of the
 * hog function, as `resolveAwsSigV4Credentials` describes. Otherwise they come from the AWS connection in that
 * input: its access keys, or temporary credentials from a two-hop assume. The worker identity assumes PostHog's
 * external role, and that session assumes the customer's role with the external ID `posthog-<organization_id>`.
 *
 * Temporary credentials stay in the memory of this process. They never go onto the queue payload or into Hog
 * globals, and each worker caches them per connection until shortly before they expire.
 */
export class AwsSigV4CredentialsService {
    private sessions = new Map<number, RoleSession>()
    private workerStsClient?: StsClientLike

    constructor(
        private config: AwsSigV4CredentialsConfig,
        private deps: AwsSigV4CredentialsDependencies
    ) {
        this.deps.pubSub.on<{ integrationIds?: number[] }>('reload-integrations', ({ integrationIds }) => {
            for (const id of integrationIds ?? []) {
                this.sessions.delete(id)
            }
        })
    }

    async resolve(
        sigv4: CyclotronInvocationQueueParametersFetchAwsSigV4Type,
        hogFunction: Pick<HogFunctionType, 'team_id' | 'inputs' | 'encrypted_inputs'>,
        url: string
    ): Promise<ResolvedAwsSigV4Credentials> {
        const integrationId = sigv4.integration_input
            ? resolveHogFunctionInputValue(hogFunction, sigv4.integration_input)
            : undefined
        if (integrationId === undefined || integrationId === null || integrationId === '') {
            return resolveAwsSigV4Credentials(sigv4, hogFunction)
        }

        const integration =
            typeof integrationId === 'number' ? await this.deps.integrationManager.get(integrationId) : null
        // A connection of another team is reported as missing, so a function cannot find out that it exists.
        if (!integration || integration.team_id !== hogFunction.team_id) {
            return failed(
                `the AWS connection in input '${sigv4.integration_input}' does not exist. Select a connection for this destination.`
            )
        }
        const connectionKind = CONNECTION_KINDS[integration.kind]
        if (!connectionKind) {
            return failed(`the connection in input '${sigv4.integration_input}' is not an AWS connection.`)
        }
        const origin = (this.deps.serviceOrigin ?? defaultServiceOrigin)(connectionKind.service, sigv4.region)
        if (
            sigv4.service !== connectionKind.service ||
            !AWS_REGION_RE.test(sigv4.region) ||
            URL.parse(url)?.origin !== origin
        ) {
            return failed(
                `the AWS connection in input '${sigv4.integration_input}' signs only requests to ${defaultServiceOrigin(connectionKind.service, '<region>')}.`
            )
        }

        const roleArn = integration.config?.aws_role_arn
        if (typeof roleArn !== 'string' || !roleArn) {
            return this.resolveAccessKeys(sigv4, integration)
        }

        if (!this.config.externalRoleArn) {
            awsRoleCredentialsCounter.inc({ result: 'not_configured' })
            return failed(
                'connections with an IAM role are not available on this PostHog instance. Connect with access keys instead.'
            )
        }

        const team = await this.deps.teamManager.getTeam(integration.team_id)
        if (!team) {
            return failed(`the team of the AWS connection in input '${sigv4.integration_input}' does not exist.`)
        }

        const session = await this.getRoleCredentials({
            integrationId: integration.id,
            teamId: integration.team_id,
            roleArn,
            externalId: `posthog-${team.organization_id}`,
            sessionActions: connectionKind.sessionActions,
        })
        if (!session.ok) {
            return session
        }

        return {
            ok: true,
            credentials: {
                service: sigv4.service,
                region: sigv4.region,
                access_key_id: session.credentials.accessKeyId,
                secret_access_key: session.credentials.secretAccessKey,
                session_token: session.credentials.sessionToken,
            },
        }
    }

    private resolveAccessKeys(
        sigv4: CyclotronInvocationQueueParametersFetchAwsSigV4Type,
        integration: IntegrationType
    ): ResolvedAwsSigV4Credentials {
        const accessKeyId = integration.sensitive_config?.aws_access_key_id
        const secretAccessKey = integration.sensitive_config?.aws_secret_access_key
        if (
            typeof accessKeyId !== 'string' ||
            !accessKeyId ||
            typeof secretAccessKey !== 'string' ||
            !secretAccessKey
        ) {
            return failed(
                `the AWS connection in input '${sigv4.integration_input}' has no IAM role and no access keys. Connect it again.`
            )
        }
        return {
            ok: true,
            credentials: {
                service: sigv4.service,
                region: sigv4.region,
                access_key_id: accessKeyId,
                secret_access_key: secretAccessKey,
            },
        }
    }

    private async getRoleCredentials(
        request: RoleRequest
    ): Promise<{ ok: true; credentials: TemporaryCredentials } | { ok: false; error: string; retryAfterMs?: number }> {
        let session = this.sessions.get(request.integrationId)
        if (!session || session.roleArn !== request.roleArn) {
            session = { roleArn: request.roleArn }
            this.sessions.set(request.integrationId, session)
        }
        const current = session

        if (isUsable(current.credentials, REFRESH_BEFORE_EXPIRY_MS)) {
            awsRoleCredentialsCounter.inc({ result: 'cache_hit' })
            return { ok: true, credentials: current.credentials }
        }

        const waitingForRetry = !!current.failure && current.failure.retryAt > Date.now()
        if (!current.pendingAssume && !waitingForRetry) {
            current.pendingAssume = this.assume(current, request).finally(() => {
                current.pendingAssume = undefined
            })
        }
        if (current.pendingAssume) {
            await current.pendingAssume
        } else {
            awsRoleCredentialsCounter.inc({ result: 'retry_wait' })
        }

        // Credentials from before a failed refresh stay valid until they expire, so they are still used.
        if (isUsable(current.credentials, MIN_REMAINING_VALIDITY_MS)) {
            return { ok: true, credentials: current.credentials }
        }
        const failure = current.failure
        return {
            ok: false,
            error: failure?.error ?? `AWS SigV4 signing failed: could not assume the AWS role ${request.roleArn}.`,
            retryAfterMs: failure?.transient ? Math.max(failure.retryAt - Date.now(), 0) : undefined,
        }
    }

    private async assume(session: RoleSession, request: RoleRequest): Promise<void> {
        const deadline = new AbortController()
        const timer = setTimeout(() => deadline.abort(), ASSUME_DEADLINE_MS)
        try {
            session.credentials = await Promise.race([
                this.assumeCustomerRole(request, deadline.signal),
                // The SDK may not observe the abort signal while it resolves the worker credentials.
                new Promise<never>((_, reject) =>
                    deadline.signal.addEventListener('abort', () =>
                        reject(
                            new AwsRoleAssumeError(
                                `AWS SigV4 signing failed: AWS STS did not answer within ${ASSUME_DEADLINE_MS / 1000} seconds for the role ${request.roleArn}.`,
                                true
                            )
                        )
                    )
                ),
            ])
            session.failure = undefined
            awsRoleCredentialsCounter.inc({ result: 'assumed' })
        } catch (error) {
            const transient = error instanceof AwsRoleAssumeError ? error.transient : true
            session.failure = {
                error:
                    error instanceof AwsRoleAssumeError
                        ? error.message
                        : `AWS SigV4 signing failed: could not assume the AWS role ${request.roleArn}.`,
                retryAt: Date.now() + (transient ? TRANSIENT_FAILURE_RETRY_DELAY_MS : FAILURE_RETRY_DELAY_MS),
                transient,
            }
        } finally {
            clearTimeout(timer)
        }
    }

    private async assumeCustomerRole(request: RoleRequest, abortSignal: AbortSignal): Promise<TemporaryCredentials> {
        // The customer filters CloudTrail by this name to find the sessions of PostHog.
        const roleSessionName = `PostHog-destinations-team-${request.teamId}`

        let externalRoleCredentials: TemporaryCredentials
        try {
            this.workerStsClient ??= this.createStsClient()
            externalRoleCredentials = toTemporaryCredentials(
                await this.workerStsClient.send(
                    new AssumeRoleCommand({
                        RoleArn: this.config.externalRoleArn,
                        RoleSessionName: roleSessionName,
                        DurationSeconds: SESSION_DURATION_SECONDS,
                        Policy: sessionPolicy('sts:AssumeRole', request.roleArn),
                    }),
                    { abortSignal }
                )
            )
        } catch (error) {
            awsRoleCredentialsCounter.inc({ result: 'external_role_failed' })
            logger.error('[AwsSigV4Credentials] Could not assume the PostHog external role', {
                error: error instanceof Error ? error.message : String(error),
                teamId: request.teamId,
                integrationId: request.integrationId,
            })
            throw new AwsRoleAssumeError(
                `AWS SigV4 signing failed: PostHog could not start an AWS session to assume the role ${request.roleArn}. This is a problem on the PostHog side. Contact support if it continues.`,
                isTransientStsError(error)
            )
        }

        const customerStsClient = this.createStsClient(externalRoleCredentials)
        try {
            return toTemporaryCredentials(
                await customerStsClient.send(
                    new AssumeRoleCommand({
                        RoleArn: request.roleArn,
                        RoleSessionName: roleSessionName,
                        ExternalId: request.externalId,
                        DurationSeconds: SESSION_DURATION_SECONDS,
                        Policy: sessionPolicy(request.sessionActions, '*'),
                    }),
                    { abortSignal }
                )
            )
        } catch (error) {
            awsRoleCredentialsCounter.inc({ result: 'customer_role_failed' })
            // Only an AWS error response goes into the function logs. Network errors can name internal addresses.
            const reason = error instanceof STSServiceException ? ` (${error.name}: ${error.message})` : ''
            throw new AwsRoleAssumeError(
                `AWS SigV4 signing failed: could not assume the AWS role ${request.roleArn} with the external ID ${request.externalId}${reason}. Check that the trust policy of the role lets PostHog assume it with this external ID.`,
                isTransientStsError(error)
            )
        } finally {
            customerStsClient.destroy()
        }
    }

    private createStsClient(credentials?: TemporaryCredentials): StsClientLike {
        if (this.deps.createStsClient) {
            return this.deps.createStsClient(credentials)
        }
        // A plain SDK client, not cdpTrackedFetch: the regional STS hostname resolves to a VPC endpoint with a
        // private address, which the SSRF guard of the destination fetch refuses.
        return new STSClient({
            region: this.config.stsRegion || undefined,
            requestHandler: new NodeHttpHandler({
                connectionTimeout: STS_CONNECTION_TIMEOUT_MS,
                requestTimeout: STS_REQUEST_TIMEOUT_MS,
                throwOnRequestTimeout: true,
            }),
            ...(credentials
                ? {
                      credentials: {
                          accessKeyId: credentials.accessKeyId,
                          secretAccessKey: credentials.secretAccessKey,
                          sessionToken: credentials.sessionToken,
                      },
                  }
                : {}),
        })
    }
}
