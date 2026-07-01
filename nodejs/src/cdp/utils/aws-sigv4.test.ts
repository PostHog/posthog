import { CyclotronInvocationQueueParametersFetchAwsSigV4Type } from '~/cdp/schema/cyclotron'

import { HogFunctionType } from '../types'
import { resolveAwsSigV4Credentials, signAwsRequest } from './aws-sigv4'

describe('signAwsRequest', () => {
    const fixedNow = new Date('2015-08-30T12:36:00Z')

    // AWS published test vector: get-vanilla
    // https://docs.aws.amazon.com/general/latest/gr/sigv4_signing.html
    // Service: 'service', region: 'us-east-1'
    // AKID: AKIDEXAMPLE / SK: wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY
    // Expected signature: 5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31
    it('matches AWS get-vanilla test vector', () => {
        const headers = signAwsRequest({
            method: 'GET',
            url: 'https://example.amazonaws.com/',
            body: '',
            credentials: {
                service: 'service',
                region: 'us-east-1',
                access_key_id: 'AKIDEXAMPLE',
                secret_access_key: 'wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY',
            },
            now: fixedNow,
        })

        expect(headers['X-Amz-Date']).toBe('20150830T123600Z')
        expect(headers.Authorization).toBe(
            'AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/service/aws4_request, ' +
                'SignedHeaders=host;x-amz-date, ' +
                'Signature=5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31'
        )
    })

    // Smoke test: same inputs at the same time yield the same signature.
    it('is deterministic for a fixed timestamp', () => {
        const args = {
            method: 'POST',
            url: 'https://kinesis.us-east-1.amazonaws.com/',
            body: '{"StreamName":"s","PartitionKey":"p","Data":"ZA=="}',
            headers: {
                'Content-Type': 'application/x-amz-json-1.1',
                'X-Amz-Target': 'Kinesis_20131202.PutRecord',
            },
            credentials: {
                service: 'kinesis',
                region: 'us-east-1',
                access_key_id: 'AKIDEXAMPLE',
                secret_access_key: 'wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY',
            },
            now: fixedNow,
        }
        expect(signAwsRequest(args)).toEqual(signAwsRequest(args))
    })

    // Re-signing must produce a different signature/timestamp when `now` advances —
    // this is the property the cyclotron retry path relies on to avoid AWS's
    // 5-minute signature expiry window.
    it('produces a fresh signature when re-signed with a later timestamp', () => {
        const base = {
            method: 'POST',
            url: 'https://kinesis.us-east-1.amazonaws.com/',
            body: '{}',
            credentials: {
                service: 'kinesis',
                region: 'us-east-1',
                access_key_id: 'AKIDEXAMPLE',
                secret_access_key: 'wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY',
            },
        }
        const first = signAwsRequest({ ...base, now: new Date('2026-06-22T07:28:57Z') })
        const second = signAwsRequest({ ...base, now: new Date('2026-06-22T07:35:54Z') })

        expect(first['X-Amz-Date']).toBe('20260622T072857Z')
        expect(second['X-Amz-Date']).toBe('20260622T073554Z')
        expect(first.Authorization).not.toBe(second.Authorization)
    })

    // Stale signing artifacts inherited from a previous attempt's queue payload
    // must be discarded — otherwise we'd resign on top of an old Authorization.
    it('strips stale Authorization and X-Amz-Date headers before re-signing', () => {
        const headers = signAwsRequest({
            method: 'POST',
            url: 'https://kinesis.us-east-1.amazonaws.com/',
            body: '{}',
            headers: {
                'Content-Type': 'application/x-amz-json-1.1',
                Authorization: 'AWS4-HMAC-SHA256 Credential=STALE/19700101/us-east-1/kinesis/aws4_request, ...',
                'X-Amz-Date': '19700101T000000Z',
            },
            credentials: {
                service: 'kinesis',
                region: 'us-east-1',
                access_key_id: 'AKIDEXAMPLE',
                secret_access_key: 'wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY',
            },
            now: fixedNow,
        })

        expect(headers.Authorization).not.toContain('STALE')
        expect(headers.Authorization).toContain('Credential=AKIDEXAMPLE/20150830/us-east-1/kinesis/aws4_request')
        expect(headers['X-Amz-Date']).toBe('20150830T123600Z')
    })

    it('includes X-Amz-Security-Token in signed headers when session token is provided', () => {
        const headers = signAwsRequest({
            method: 'POST',
            url: 'https://kinesis.us-east-1.amazonaws.com/',
            body: '{}',
            credentials: {
                service: 'kinesis',
                region: 'us-east-1',
                access_key_id: 'AKIDEXAMPLE',
                secret_access_key: 'wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY',
                session_token: 'session-token-value',
            },
            now: fixedNow,
        })

        expect(headers['X-Amz-Security-Token']).toBe('session-token-value')
        expect(headers.Authorization).toContain('x-amz-security-token')
    })

    it('derives Host from the URL', () => {
        const headers = signAwsRequest({
            method: 'POST',
            url: 'https://kinesis.eu-central-1.amazonaws.com/',
            body: '{}',
            credentials: {
                service: 'kinesis',
                region: 'eu-central-1',
                access_key_id: 'AKIDEXAMPLE',
                secret_access_key: 'wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY',
            },
            now: fixedNow,
        })

        expect(headers.Host).toBe('kinesis.eu-central-1.amazonaws.com')
    })

    // Regression for the pre-refactor Hog-side signer. Before signing moved out of
    // the Kinesis Hog template, `test_template_aws_kinesis.py` asserted the exact
    // outgoing Authorization header for this frozen time + input fixture, including
    // the signature hex `65b18913...`. If the Node signer ever diverges from that
    // shape we lose backwards compatibility with the prior production signatures
    // and any external system relying on identical canonical-request semantics.
    it('matches the in-Hog Kinesis signer for the test_template_aws_kinesis fixture', () => {
        const headers = signAwsRequest({
            method: 'POST',
            url: 'https://kinesis.aws_region.amazonaws.com',
            body: '{"StreamName": "aws_kinesis_stream_arn", "PartitionKey": "1", "Data": "eyJoZWxsbyI6ICJ3b3JsZCJ9"}',
            headers: {
                'Content-Type': 'application/x-amz-json-1.1',
                'X-Amz-Target': 'Kinesis_20131202.PutRecord',
            },
            credentials: {
                service: 'kinesis',
                region: 'aws_region',
                access_key_id: 'aws_access_key_id',
                secret_access_key: 'aws_secret_access_key',
            },
            now: new Date('2024-04-16T12:34:51Z'),
        })

        expect(headers).toEqual({
            'Content-Type': 'application/x-amz-json-1.1',
            'X-Amz-Target': 'Kinesis_20131202.PutRecord',
            'X-Amz-Date': '20240416T123451Z',
            Host: 'kinesis.aws_region.amazonaws.com',
            Authorization:
                'AWS4-HMAC-SHA256 Credential=aws_access_key_id/20240416/aws_region/kinesis/aws4_request, ' +
                'SignedHeaders=content-type;host;x-amz-date;x-amz-target, ' +
                'Signature=65b18913b42d8a7a1d33c0711da192d5a2e99eb79fb08ab3e5eefb6488b903ff',
        })
    })

    // Regression guard: a malformed percent-encoded query segment (e.g.
    // `?metric=p95%tile` or a bare `%`) used to crash `decodeURIComponent`
    // and let a URIError bubble out of `signAwsRequest`, failing the entire
    // fetch attempt instead of producing a signature. Kinesis doesn't carry
    // query strings, but the canonical-query-string code is general-purpose
    // and ships with SQS / EventBridge ambitions.
    it('does not throw on malformed percent-encoded query strings', () => {
        expect(() =>
            signAwsRequest({
                method: 'GET',
                url: 'https://kinesis.us-east-1.amazonaws.com/?metric=p95%tile&ok=hello%20world&bad=%',
                body: '',
                credentials: {
                    service: 'kinesis',
                    region: 'us-east-1',
                    access_key_id: 'AKIDEXAMPLE',
                    secret_access_key: 'wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY',
                },
                now: fixedNow,
            })
        ).not.toThrow()
    })
})

describe('resolveAwsSigV4Credentials', () => {
    const sigv4Refs: CyclotronInvocationQueueParametersFetchAwsSigV4Type = {
        service: 'kinesis',
        region: 'us-east-1',
        access_key_id_input: 'aws_access_key_id',
        secret_access_key_input: 'aws_secret_access_key',
    }

    const hogFunctionWith = (
        encrypted: Record<string, { value: unknown }> | null = null,
        inputs: Record<string, { value: unknown }> | null = null
    ): Pick<HogFunctionType, 'inputs' | 'encrypted_inputs'> =>
        ({
            inputs: inputs as any,
            encrypted_inputs: encrypted as any,
        }) as Pick<HogFunctionType, 'inputs' | 'encrypted_inputs'>

    it('resolves credentials from encrypted_inputs (the production path for secret: true)', () => {
        const result = resolveAwsSigV4Credentials(
            sigv4Refs,
            hogFunctionWith({
                aws_access_key_id: { value: 'AKIDEXAMPLE' },
                aws_secret_access_key: { value: 'wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY' },
            })
        )

        expect(result.ok).toBe(true)
        if (result.ok) {
            expect(result.credentials.access_key_id).toBe('AKIDEXAMPLE')
            expect(result.credentials.secret_access_key).toBe('wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY')
            expect(result.credentials.region).toBe('us-east-1')
            expect(result.credentials.service).toBe('kinesis')
            expect(result.credentials.session_token).toBeUndefined()
        }
    })

    it('falls back to plaintext inputs when encrypted_inputs is missing the key', () => {
        const result = resolveAwsSigV4Credentials(
            sigv4Refs,
            hogFunctionWith(null, {
                aws_access_key_id: { value: 'AKIDEXAMPLE' },
                aws_secret_access_key: { value: 'wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY' },
            })
        )

        expect(result.ok).toBe(true)
    })

    it('returns the encrypted_inputs value when both fields define the key', () => {
        const result = resolveAwsSigV4Credentials(
            sigv4Refs,
            hogFunctionWith(
                {
                    aws_access_key_id: { value: 'FROM_ENCRYPTED' },
                    aws_secret_access_key: { value: 'SECRET_ENCRYPTED' },
                },
                {
                    aws_access_key_id: { value: 'FROM_PLAINTEXT' },
                    aws_secret_access_key: { value: 'SECRET_PLAINTEXT' },
                }
            )
        )

        expect(result.ok).toBe(true)
        if (result.ok) {
            expect(result.credentials.access_key_id).toBe('FROM_ENCRYPTED')
            expect(result.credentials.secret_access_key).toBe('SECRET_ENCRYPTED')
        }
    })

    it('reports both missing inputs in the error message', () => {
        const result = resolveAwsSigV4Credentials(sigv4Refs, hogFunctionWith())
        expect(result.ok).toBe(false)
        if (!result.ok) {
            expect(result.error).toContain('aws_access_key_id')
            expect(result.error).toContain('aws_secret_access_key')
            expect(result.error).toContain('Refusing to send an unsigned request')
        }
    })

    it('reports only the missing input when only one is absent', () => {
        const result = resolveAwsSigV4Credentials(
            sigv4Refs,
            hogFunctionWith({ aws_access_key_id: { value: 'AKIDEXAMPLE' } })
        )
        expect(result.ok).toBe(false)
        if (!result.ok) {
            expect(result.error).toContain('aws_secret_access_key')
            expect(result.error).not.toContain('aws_access_key_id')
        }
    })

    it('treats non-string values as missing (defensive: an int or null would silently break signing)', () => {
        const result = resolveAwsSigV4Credentials(
            sigv4Refs,
            hogFunctionWith({
                aws_access_key_id: { value: 12345 },
                aws_secret_access_key: { value: null },
            })
        )
        expect(result.ok).toBe(false)
    })

    it('includes session_token when session_token_input is provided and resolves', () => {
        const result = resolveAwsSigV4Credentials(
            { ...sigv4Refs, session_token_input: 'aws_session_token' },
            hogFunctionWith({
                aws_access_key_id: { value: 'AKIDEXAMPLE' },
                aws_secret_access_key: { value: 'wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY' },
                aws_session_token: { value: 'session-token-value' },
            })
        )

        expect(result.ok).toBe(true)
        if (result.ok) {
            expect(result.credentials.session_token).toBe('session-token-value')
        }
    })

    // A missing optional session token should not fail-closed — the request is
    // still signable with just the long-term credentials.
    it('skips session_token when session_token_input is set but the input is missing', () => {
        const result = resolveAwsSigV4Credentials(
            { ...sigv4Refs, session_token_input: 'aws_session_token' },
            hogFunctionWith({
                aws_access_key_id: { value: 'AKIDEXAMPLE' },
                aws_secret_access_key: { value: 'wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY' },
            })
        )

        expect(result.ok).toBe(true)
        if (result.ok) {
            expect(result.credentials.session_token).toBeUndefined()
        }
    })
})
