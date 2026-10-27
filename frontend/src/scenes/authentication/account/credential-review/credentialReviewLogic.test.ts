import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import type { ConnectedAppApi } from '~/generated/core/api.schemas'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { credentialReviewLogic } from './credentialReviewLogic'

const REVIEW_COMPLETE_URL = '/api/users/@me/credentials_review_complete/'

function connectedApp(id: string, flags: Partial<ConnectedAppApi>): ConnectedAppApi {
    return {
        id,
        name: id,
        logo_uri: null,
        scopes: ['project:read'],
        authorized_at: '2026-08-01T09:12:00Z',
        is_verified: false,
        is_first_party: false,
        requires_access_confirmation: false,
        is_self_registered: false,
        ...flags,
    }
}

const UNVERIFIED_PARTNER_A = connectedApp('partner-a', { requires_access_confirmation: true })
const UNVERIFIED_PARTNER_B = connectedApp('partner-b', { requires_access_confirmation: true })
const ORDINARY_APP = connectedApp('ordinary-app', {})

function postedUrls(): string[] {
    return jest.mocked(api.create).mock.calls.map(([url]) => url)
}

describe('credentialReviewLogic', () => {
    let connectedApps: ConnectedAppApi[]
    let connectedAppsStatus: number

    beforeEach(() => {
        connectedApps = []
        connectedAppsStatus = 200
        useMocks({
            get: {
                '/api/users/@me/': () => [200, MOCK_DEFAULT_USER],
                '/api/personal_api_keys/': () => [200, []],
                '/api/webauthn/credentials/': () => [200, []],
                '/api/oauth/connected-apps/': () => [connectedAppsStatus, connectedApps],
            },
        })
        initKeaTests()
        userLogic.mount()
        jest.spyOn(api, 'create').mockResolvedValue({})
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    test.each([
        [
            'returns to the page the user was on',
            '/data-warehouse/new-source?kind=Hubspot#configure',
            '/data-warehouse/new-source?kind=Hubspot#configure',
        ],
        ['ignores an off-site next', 'https://example.com/phish', urls.projectHomepage()],
    ])('Continue %s', async (_, next, expectedPath) => {
        router.actions.push(urls.credentialReview(next))
        const logic = credentialReviewLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.markComplete()
        await expectLogic(logic).toFinishAllListeners()

        const actualPath = router.values.location.pathname + router.values.location.search + router.values.location.hash
        expect(removeProjectIdIfPresent(actualPath)).toEqual(removeProjectIdIfPresent(expectedPath))
    })

    test('Continue waits until every app that needs confirmation has a choice', async () => {
        connectedApps = [UNVERIFIED_PARTNER_A, UNVERIFIED_PARTNER_B, ORDINARY_APP]
        const logic = credentialReviewLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.markComplete()
        await expectLogic(logic).toFinishAllListeners()
        expect(postedUrls()).toEqual([])

        logic.actions.keepPartnerConnected(UNVERIFIED_PARTNER_A.id)
        logic.actions.markComplete()
        await expectLogic(logic).toFinishAllListeners()
        expect(postedUrls()).toEqual([])

        logic.actions.keepPartnerConnected(UNVERIFIED_PARTNER_B.id)
        logic.actions.markComplete()
        logic.actions.markComplete()
        await expectLogic(logic).toFinishAllListeners()
        expect(postedUrls()).toEqual([REVIEW_COMPLETE_URL])
    })

    test('Continue stays disabled when the connected apps fail to load', async () => {
        connectedAppsStatus = 500
        const logic = credentialReviewLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.markComplete()
        await expectLogic(logic).toFinishAllListeners()
        expect(postedUrls()).toEqual([])
    })

    test('Disconnect revokes the partner once and unblocks Continue', async () => {
        connectedApps = [UNVERIFIED_PARTNER_A]
        const logic = credentialReviewLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.disconnectPartner(UNVERIFIED_PARTNER_A.id)
        logic.actions.disconnectPartner(UNVERIFIED_PARTNER_A.id)
        await expectLogic(logic).toFinishAllListeners()
        expect(postedUrls()).toEqual([`/api/oauth/connected-apps/${UNVERIFIED_PARTNER_A.id}/revoke/`])

        logic.actions.markComplete()
        await expectLogic(logic).toFinishAllListeners()
        expect(postedUrls()).toEqual([
            `/api/oauth/connected-apps/${UNVERIFIED_PARTNER_A.id}/revoke/`,
            REVIEW_COMPLETE_URL,
        ])
    })

    test('Disconnect is ignored while the review is being saved', async () => {
        connectedApps = [UNVERIFIED_PARTNER_A]
        const logic = credentialReviewLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.keepPartnerConnected(UNVERIFIED_PARTNER_A.id)
        logic.actions.markComplete()
        logic.actions.disconnectPartner(UNVERIFIED_PARTNER_A.id)
        await expectLogic(logic).toFinishAllListeners()

        expect(postedUrls()).toEqual([REVIEW_COMPLETE_URL])
    })
})
