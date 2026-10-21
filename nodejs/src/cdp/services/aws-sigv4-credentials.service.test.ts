import { AssumeRoleCommand, AssumeRoleCommandInput, STSServiceException } from '@aws-sdk/client-sts'
import { register } from 'prom-client'

import { parseJSON } from '~/common/utils/json-parse'
import { Team } from '~/types'

import { CyclotronInvocationQueueParametersFetchAwsSigV4Type } from '../schema/cyclotron'
import { HogFunctionType, IntegrationType } from '../types'
import { AwsSigV4CredentialsService, StsClientLike } from './aws-sigv4-credentials.service'

const TEAM_ID = 2
const ORGANIZATION_ID = '01234567-89ab-cdef-0123-456789abcdef'
const INTEGRATION_ID = 7
const EXTERNAL_ROLE_ARN = 'arn:aws:iam::111111111111:role/posthog-external-example'
const CUSTOMER_ROLE_ARN = 'arn:aws:iam::222222222222:role/kinesis-writer'
const KINESIS_URL = 'https://kinesis.eu-west-1.amazonaws.com'
const START = Date.UTC(2025, 0, 1)
const MINUTE = 60 * 1000

const sigv4: CyclotronInvocationQueueParametersFetchAwsSigV4Type = {
    service: 'kinesis',
    region: 'eu-west-1',
    access_key_id_input: 'aws_access_key_id',
    secret_access_key_input: 'aws_secret_access_key',
    integration_input: 'aws_connection',
}

type StsCall = { caller: 'worker' | 'external-role-session'; input: AssumeRoleCommandInput }

describe('AwsSigV4CredentialsService', () => {
    let now: number
    let stsCalls: StsCall[]
    let customerRoleError: Error | null
    let integration: IntegrationType
    let reloadIntegrations: (message: { integrationIds?: number[] }) => void
    let assumeCount: number

    const hogFunction = (
        value: unknown = INTEGRATION_ID
    ): Pick<HogFunctionType, 'team_id' | 'inputs' | 'encrypted_inputs'> => ({
        team_id: TEAM_ID,
        inputs: { aws_connection: { value } },
        encrypted_inputs: {
            aws_access_key_id: { value: 'AKIAINPUTEXAMPLE' },
            aws_secret_access_key: { value: 'input-secret-example' },
        },
    })

    const createService = (externalRoleArn = EXTERNAL_ROLE_ARN): AwsSigV4CredentialsService =>
        new AwsSigV4CredentialsService(
            { externalRoleArn, stsRegion: 'us-east-1' },
            {
                integrationManager: { get: (id) => Promise.resolve(id === integration.id ? integration : null) },
                teamManager: {
                    getTeam: (id) =>
                        Promise.resolve(id === TEAM_ID ? ({ id, organization_id: ORGANIZATION_ID } as Team) : null),
                },
                pubSub: {
                    on: (channel: string, listener: (message: any) => void) => {
                        if (channel === 'reload-integrations') {
                            reloadIntegrations = listener
                        }
                    },
                },
                createStsClient: (credentials): StsClientLike => ({
                    send: (command: AssumeRoleCommand) => {
                        stsCalls.push({
                            caller: credentials ? 'external-role-session' : 'worker',
                            input: command.input,
                        })
                        if (credentials && customerRoleError) {
                            return Promise.reject(customerRoleError)
                        }
                        assumeCount++
                        return Promise.resolve({
                            Credentials: {
                                AccessKeyId: `ASIA${assumeCount}`,
                                SecretAccessKey: `secret-${assumeCount}`,
                                SessionToken: `session-token-${assumeCount}`,
                                Expiration: new Date(now + 60 * MINUTE),
                            },
                            $metadata: {},
                        })
                    },
                    destroy: () => {},
                }),
            }
        )

    const roleMetric = async (result: string): Promise<number> => {
        const metric = await register.getSingleMetric('cdp_aws_role_credentials_total')?.get()
        return metric?.values.find((value) => value.labels.result === result)?.value ?? 0
    }

    beforeEach(() => {
        now = START
        jest.spyOn(Date, 'now').mockImplementation(() => now)
        stsCalls = []
        customerRoleError = null
        assumeCount = 0
        integration = {
            id: INTEGRATION_ID,
            team_id: TEAM_ID,
            kind: 'aws-kinesis',
            config: { name: 'stream writer', aws_role_arn: CUSTOMER_ROLE_ARN },
            sensitive_config: {},
        }
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('assumes the customer role through the PostHog role, with a narrow session at each hop', async () => {
        const result = await createService().resolve(sigv4, hogFunction(), KINESIS_URL)

        expect(result).toEqual({
            ok: true,
            credentials: {
                service: 'kinesis',
                region: 'eu-west-1',
                access_key_id: 'ASIA2',
                secret_access_key: 'secret-2',
                session_token: 'session-token-2',
            },
        })
        expect(stsCalls.map(({ caller, input }) => ({ caller, ...input, Policy: parseJSON(input.Policy!) }))).toEqual([
            {
                caller: 'worker',
                RoleArn: EXTERNAL_ROLE_ARN,
                RoleSessionName: `PostHog-destinations-team-${TEAM_ID}`,
                DurationSeconds: 3600,
                Policy: {
                    Version: '2012-10-17',
                    Statement: [{ Effect: 'Allow', Action: 'sts:AssumeRole', Resource: CUSTOMER_ROLE_ARN }],
                },
            },
            {
                caller: 'external-role-session',
                RoleArn: CUSTOMER_ROLE_ARN,
                RoleSessionName: `PostHog-destinations-team-${TEAM_ID}`,
                ExternalId: `posthog-${ORGANIZATION_ID}`,
                DurationSeconds: 3600,
                Policy: {
                    Version: '2012-10-17',
                    Statement: [
                        {
                            Effect: 'Allow',
                            Action: ['kinesis:PutRecord', 'kinesis:PutRecords', 'kms:GenerateDataKey'],
                            Resource: '*',
                        },
                    ],
                },
            },
        ])
    })

    it('reuses the session until it is close to expiry, then assumes the role again', async () => {
        const service = createService()

        await service.resolve(sigv4, hogFunction(), KINESIS_URL)
        now += 45 * MINUTE
        const cached = await service.resolve(sigv4, hogFunction(), KINESIS_URL)
        expect(stsCalls).toHaveLength(2)
        expect(cached).toMatchObject({ ok: true, credentials: { session_token: 'session-token-2' } })

        now += 10 * MINUTE
        const refreshed = await service.resolve(sigv4, hogFunction(), KINESIS_URL)
        expect(stsCalls).toHaveLength(4)
        expect(refreshed).toMatchObject({ ok: true, credentials: { session_token: 'session-token-4' } })
    })

    it('shares one assume between lookups that arrive together', async () => {
        const service = createService()

        const results = await Promise.all([1, 2, 3].map(() => service.resolve(sigv4, hogFunction(), KINESIS_URL)))

        expect(stsCalls).toHaveLength(2)
        expect(new Set(results.map((result) => result.ok && result.credentials.session_token))).toEqual(
            new Set(['session-token-2'])
        )
    })

    it('assumes the role again after a reload-integrations message for the connection', async () => {
        const service = createService()
        await service.resolve(sigv4, hogFunction(), KINESIS_URL)

        reloadIntegrations({ integrationIds: [INTEGRATION_ID + 1] })
        await service.resolve(sigv4, hogFunction(), KINESIS_URL)
        expect(stsCalls).toHaveLength(2)

        reloadIntegrations({ integrationIds: [INTEGRATION_ID] })
        await service.resolve(sigv4, hogFunction(), KINESIS_URL)
        expect(stsCalls).toHaveLength(4)
    })

    it('fails with the role and external ID when AWS denies the customer role, then waits before it retries', async () => {
        customerRoleError = new STSServiceException({
            name: 'AccessDenied',
            $fault: 'client',
            $metadata: {},
            message: 'Not authorized to perform sts:AssumeRole',
        })
        const service = createService()

        const result = await service.resolve(sigv4, hogFunction(), KINESIS_URL)

        expect(result).toEqual({
            ok: false,
            error: `AWS SigV4 signing failed: could not assume the AWS role ${CUSTOMER_ROLE_ARN} with the external ID posthog-${ORGANIZATION_ID} (AccessDenied: Not authorized to perform sts:AssumeRole). Check that the trust policy of the role lets PostHog assume it with this external ID.`,
        })

        now += 30 * 1000
        expect(await service.resolve(sigv4, hogFunction(), KINESIS_URL)).toEqual(result)
        expect(stsCalls).toHaveLength(2)

        customerRoleError = null
        now += 31 * 1000
        expect(await service.resolve(sigv4, hogFunction(), KINESIS_URL)).toMatchObject({ ok: true })
        expect(stsCalls).toHaveLength(4)
    })

    it.each([
        [
            'throttling',
            new STSServiceException({ name: 'Throttling', $fault: 'client', $metadata: {}, message: 'Rate exceeded' }),
            10_000,
        ],
        [
            'a server fault',
            new STSServiceException({ name: 'InternalFailure', $fault: 'server', $metadata: {}, message: 'Internal' }),
            10_000,
        ],
        ['a network error', new Error('connect ETIMEDOUT'), 10_000],
        [
            'access denied',
            new STSServiceException({ name: 'AccessDenied', $fault: 'client', $metadata: {}, message: 'Denied' }),
            undefined,
        ],
    ])('asks the caller to retry after %s only when it can pass', async (_name, error, retryAfterMs) => {
        customerRoleError = error

        const result = await createService().resolve(sigv4, hogFunction(), KINESIS_URL)

        expect(result).toMatchObject({ ok: false })
        expect(result.ok === false && result.retryAfterMs).toBe(retryAfterMs)
    })

    it('ends an assume that STS never answers, so later lookups are not blocked', async () => {
        jest.useFakeTimers({ doNotFake: ['Date', 'performance'] })
        try {
            const service = new AwsSigV4CredentialsService(
                { externalRoleArn: EXTERNAL_ROLE_ARN, stsRegion: 'us-east-1' },
                {
                    integrationManager: { get: () => Promise.resolve(integration) },
                    teamManager: { getTeam: () => Promise.resolve({ organization_id: ORGANIZATION_ID } as Team) },
                    pubSub: { on: () => {} },
                    createStsClient: () => ({ send: () => new Promise(() => {}), destroy: () => {} }),
                }
            )

            const pending = service.resolve(sigv4, hogFunction(), KINESIS_URL)
            await jest.advanceTimersByTimeAsync(10_000)

            expect(await pending).toEqual({
                ok: false,
                error: `AWS SigV4 signing failed: AWS STS did not answer within 10 seconds for the role ${CUSTOMER_ROLE_ARN}.`,
                retryAfterMs: 10_000,
            })
        } finally {
            jest.useRealTimers()
        }
    })

    it('keeps using credentials that are still valid when a refresh fails', async () => {
        const service = createService()
        await service.resolve(sigv4, hogFunction(), KINESIS_URL)

        now += 55 * MINUTE
        customerRoleError = new Error('connect ETIMEDOUT')
        const result = await service.resolve(sigv4, hogFunction(), KINESIS_URL)

        expect(result).toMatchObject({ ok: true, credentials: { session_token: 'session-token-2' } })
    })

    it('fails closed and counts it when the PostHog role is not configured', async () => {
        const before = await roleMetric('not_configured')

        const result = await createService('').resolve(sigv4, hogFunction(), KINESIS_URL)

        expect(result).toEqual({
            ok: false,
            error: 'AWS SigV4 signing failed: connections with an IAM role are not available on this PostHog instance. Connect with access keys instead.',
        })
        expect(stsCalls).toEqual([])
        expect(await roleMetric('not_configured')).toBe(before + 1)
    })

    it.each([
        [
            'belongs to another team',
            (): void => void (integration.team_id = TEAM_ID + 1),
            "the AWS connection in input 'aws_connection' does not exist",
        ],
        [
            'was deleted',
            (): void => void (integration.id = INTEGRATION_ID + 1),
            "the AWS connection in input 'aws_connection' does not exist",
        ],
        [
            'is not an AWS connection',
            (): void => void (integration.kind = 'slack'),
            "the connection in input 'aws_connection' is not an AWS connection",
        ],
    ])('fails without calling AWS when the connection %s', async (_name, setup, error) => {
        setup()

        const result = await createService().resolve(sigv4, hogFunction(), KINESIS_URL)

        expect(result).toEqual({ ok: false, error: expect.stringContaining(error) })
        expect(stsCalls).toEqual([])
    })

    it.each([
        ['a host that is not the Kinesis endpoint', 'https://attacker.example.com', sigv4, false],
        ['a Kinesis URL over plain HTTP', 'http://kinesis.eu-west-1.amazonaws.com', sigv4, false],
        ['another AWS service', 'https://sts.eu-west-1.amazonaws.com', { ...sigv4, service: 'sts' }, false],
        [
            'another AWS service with access keys',
            'https://sts.eu-west-1.amazonaws.com',
            { ...sigv4, service: 'sts' },
            true,
        ],
    ])('refuses to sign a request to %s with the connection', async (_name, url, request, withAccessKeys) => {
        if (withAccessKeys) {
            integration.config = { name: 'stream writer' }
            integration.sensitive_config = {
                aws_access_key_id: 'AKIACONNECTIONEXAMPLE',
                aws_secret_access_key: 'connection-secret-example',
            }
        }

        const result = await createService().resolve(request, hogFunction(), url)

        expect(result).toEqual({
            ok: false,
            error: "AWS SigV4 signing failed: the AWS connection in input 'aws_connection' signs only requests to https://kinesis.<region>.amazonaws.com.",
        })
        expect(stsCalls).toEqual([])
    })

    it('signs with the access keys of a connection that has no IAM role', async () => {
        integration.config = { name: 'stream writer' }
        integration.sensitive_config = {
            aws_access_key_id: 'AKIACONNECTIONEXAMPLE',
            aws_secret_access_key: 'connection-secret-example',
        }

        const result = await createService().resolve(sigv4, hogFunction(), KINESIS_URL)

        expect(result).toEqual({
            ok: true,
            credentials: {
                service: 'kinesis',
                region: 'eu-west-1',
                access_key_id: 'AKIACONNECTIONEXAMPLE',
                secret_access_key: 'connection-secret-example',
            },
        })
        expect(stsCalls).toEqual([])
    })

    it.each([[null], ['']])('signs with the key inputs when the connection input is %p', async (value) => {
        const result = await createService().resolve(sigv4, hogFunction(value), KINESIS_URL)

        expect(result).toMatchObject({
            ok: true,
            credentials: { access_key_id: 'AKIAINPUTEXAMPLE', secret_access_key: 'input-secret-example' },
        })
        expect(stsCalls).toEqual([])
    })
})
