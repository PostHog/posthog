import { SSFDirectionEnumApi, SSFOutgoingEventTypeEnumApi, SSFStreamStatusEnumApi } from '~/generated/core/api.schemas'
import type { SSFConnectionApi, SSFSettingsApi, SSFStreamApi } from '~/generated/core/api.schemas'

export const SSF_SETTINGS: SSFSettingsApi = {
    enabled: true,
    event_types: [],
    event_type_options: [
        {
            key: SSFOutgoingEventTypeEnumApi.HttpsSchemasopenidnetSeceventCaepEventTypeSessionRevoked,
            label: 'Session revoked (CAEP)',
        },
        {
            key: SSFOutgoingEventTypeEnumApi.HttpsSchemasopenidnetSeceventRiscEventTypeAccountEnabled,
            label: 'Account enabled (RISC)',
        },
        {
            key: SSFOutgoingEventTypeEnumApi.HttpsSchemasopenidnetSeceventRiscEventTypeAccountDisabled,
            label: 'Account disabled (RISC)',
        },
        {
            key: SSFOutgoingEventTypeEnumApi.HttpsSchemasopenidnetSeceventRiscEventTypeCredentialCompromise,
            label: 'Credential compromise (RISC)',
        },
    ],
    endpoints: {
        issuer: 'https://posthog.example.com/ssf/example-organization',
        discovery_url: 'https://posthog.example.com/.well-known/ssf-configuration/example-organization',
        jwks_url: 'https://posthog.example.com/ssf/example-organization/jwks.json',
    },
}

export const SSF_INCOMING_CONNECTION: SSFConnectionApi = {
    id: '01980000-0000-4000-8000-000000000001',
    name: 'Example identity provider',
    direction: SSFDirectionEnumApi.Incoming,
    enabled: true,
    issuer: 'https://idp.example.com',
    audience: '',
    jwks_uri: 'https://idp.example.com/jwks.json',
    discovered_at: '2026-10-23T11:00:00Z',
    has_remote_token: true,
    has_management_token: false,
    stream_count: 2,
    created_at: '2026-10-23T11:00:00Z',
}

export const SSF_OUTGOING_CONNECTION: SSFConnectionApi = {
    id: '01980000-0000-4000-8000-000000000002',
    name: 'Example security receiver',
    direction: SSFDirectionEnumApi.Outgoing,
    enabled: true,
    issuer: '',
    audience: 'example-security-receiver',
    jwks_uri: '',
    discovered_at: null,
    has_remote_token: false,
    has_management_token: true,
    stream_count: 1,
    created_at: '2026-10-23T11:00:00Z',
}

export const SSF_INCOMING_STREAM: SSFStreamApi = {
    id: '01980000-0000-4000-8000-000000000011',
    connection: SSF_INCOMING_CONNECTION.id,
    direction: SSFDirectionEnumApi.Incoming,
    description: 'Account security events',
    status: SSFStreamStatusEnumApi.Enabled,
    reason: '',
    audiences: ['example-audience'],
    events_requested: ['https://schemas.openid.net/secevent/ssf/event-type/verification'],
    events_delivered: ['https://schemas.openid.net/secevent/ssf/event-type/verification'],
    remote_stream_id: 'upstream-stream-one',
    endpoint_url: 'https://posthog.example.com/ssf/example-organization/events/01980000-0000-4000-8000-000000000011',
    last_verified_at: null,
    last_error: '',
    retry_at: null,
    verification_pending: false,
    is_busy: false,
    created_at: '2026-10-23T11:00:00Z',
}

export const SSF_OUTGOING_STREAM: SSFStreamApi = {
    ...SSF_INCOMING_STREAM,
    id: '01980000-0000-4000-8000-000000000012',
    connection: SSF_OUTGOING_CONNECTION.id,
    direction: SSFDirectionEnumApi.Outgoing,
    description: 'Security receiver stream',
    audiences: ['example-security-receiver'],
    remote_stream_id: '',
    endpoint_url: 'https://posthog.example.com/ssf/example-organization/poll/01980000-0000-4000-8000-000000000012',
}
