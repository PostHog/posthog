import { router } from 'kea-router'

import { useMocks } from '~/mocks/jest'
import type { SourceConfig } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { availableSourcesLogic } from '../NewSourceScene/availableSourcesLogic'
import { sourceConnectSceneLogic } from './sourceConnectSceneLogic'

const AVAILABLE_SOURCES: Record<string, SourceConfig> = {
    Postgres: {
        name: 'Postgres',
        iconPath: '',
        caption: '',
        fields: [{ type: 'text', name: 'host', label: 'Host', required: true, placeholder: '' }],
    } as unknown as SourceConfig,
    Hubspot: {
        name: 'Hubspot',
        iconPath: '',
        caption: '',
        fields: [
            {
                type: 'oauth',
                name: 'hubspot_integration_id',
                label: 'Hubspot account',
                required: true,
                kind: 'hubspot',
            },
        ],
    } as unknown as SourceConfig,
    Stripe: {
        name: 'Stripe',
        iconPath: '',
        caption: '',
        fields: [
            {
                type: 'select',
                name: 'auth_method',
                label: 'Auth method',
                required: true,
                defaultValue: 'api_key',
                options: [
                    {
                        label: 'API key',
                        value: 'api_key',
                        fields: [
                            {
                                type: 'password',
                                name: 'stripe_secret_key',
                                label: 'Secret key',
                                required: true,
                                placeholder: '',
                            },
                        ],
                    },
                    {
                        label: 'OAuth',
                        value: 'oauth',
                        fields: [
                            {
                                type: 'oauth',
                                name: 'stripe_integration_id',
                                label: 'Stripe account',
                                required: true,
                                kind: 'stripe',
                            },
                        ],
                    },
                ],
            },
        ],
    } as unknown as SourceConfig,
}

describe('sourceConnectSceneLogic', () => {
    let unmountAvailableSources: () => void
    let unmountLogic: () => void

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/external_data_sources/wizard/': AVAILABLE_SOURCES,
            },
        })
        initKeaTests()
        unmountAvailableSources = availableSourcesLogic.mount()
        availableSourcesLogic.actions.loadSuccess(AVAILABLE_SOURCES)
        unmountLogic = sourceConnectSceneLogic.mount()
    })

    afterEach(() => {
        unmountLogic()
        unmountAvailableSources()
    })

    it.each([
        ['Postgres', 'Postgres'],
        ['postgres', 'Postgres'],
        ['HUBSPOT', 'Hubspot'],
    ])('resolves kind=%s to source config %s case-insensitively', (kind, expectedName) => {
        router.actions.push(`/data-warehouse/connect?kind=${kind}`)
        expect(sourceConnectSceneLogic.values.kind).toEqual(kind)
        expect(sourceConnectSceneLogic.values.sourceConfig?.name).toEqual(expectedName)
    })

    it('returns no source config for an unknown or missing kind', () => {
        router.actions.push('/data-warehouse/connect?kind=NotARealSource')
        expect(sourceConnectSceneLogic.values.sourceConfig).toBeNull()

        router.actions.push('/data-warehouse/connect')
        expect(sourceConnectSceneLogic.values.kind).toBeNull()
        expect(sourceConnectSceneLogic.values.sourceConfig).toBeNull()
    })

    it('starts with no stored credential and records one after setStoredCredential', () => {
        expect(sourceConnectSceneLogic.values.storedCredential).toBeNull()
        sourceConnectSceneLogic.actions.setStoredCredential({
            credential_id: 'ba07775f-8eaf-4d09-aa6f-50e37f17f243',
            source_type: 'Postgres',
            created_at: '2026-06-10T00:00:00Z',
            expires_at: '2026-06-11T00:00:00Z',
        })
        expect(sourceConnectSceneLogic.values.storedCredential?.credential_id).toEqual(
            'ba07775f-8eaf-4d09-aa6f-50e37f17f243'
        )
    })
})
