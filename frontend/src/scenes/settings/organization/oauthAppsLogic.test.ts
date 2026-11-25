import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { supportLogic } from 'lib/components/Support/supportLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { oauthApplicationLogic } from './OAuthApplication/oauthApplicationLogic'
import { oauthAppReviewNoteLogic } from './OAuthApplication/oauthAppReviewNoteLogic'
import { oauthAppsLogic } from './oauthAppsLogic'

const MOCK_APPS = [
    {
        id: 'app-1',
        name: 'MCP Cursor',
        client_id: 'client_abc',
        redirect_uris_list: ['https://cursor.sh/callback'],
        is_verified: true,
        is_cimd_client: false,
        provisioning_status: 'not_a_partner' as const,
        provisioning_review: null,
        created: '2026-01-15T10:00:00Z',
        updated: '2026-01-15T10:00:00Z',
    },
    {
        id: 'app-2',
        name: 'PostHog Toolbar',
        client_id: 'https://partner.example.com/.well-known/client.json',
        redirect_uris_list: ['https://partner.example.com/callback'],
        is_verified: false,
        is_cimd_client: true,
        provisioning_status: 'waiting_for_staff' as const,
        provisioning_review: {
            status: 'needs_human' as const,
            opened_at: '2026-01-10T10:00:00Z',
            decided_at: '2026-01-10T10:05:00Z',
            partner_message: '',
            timeline: [],
        },
        created: '2026-01-10T10:00:00Z',
        updated: '2026-01-10T10:00:00Z',
    },
]

const REGISTRATION = {
    client_name: 'PostHog Toolbar',
    client_uri: '',
    logo_uri: '',
    tos_uri: '',
    policy_uri: '',
    contacts: [],
    redirect_uris: [],
    jwks_uri: '',
    authentication: 'none' as const,
    scopes: [],
    uses_default_scopes: false,
    needs_signing_key: false,
    can_create_accounts: true,
    can_provision_resources: true,
    organization_link: 'this_organization' as const,
    metadata_document: '',
}

describe('oauthAppsLogic', () => {
    let logic: ReturnType<typeof oauthAppsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/organizations/:organization_id/oauth_applications/': {
                    count: MOCK_APPS.length,
                    next: null,
                    previous: null,
                    results: MOCK_APPS,
                },
            },
        })
        initKeaTests(true, undefined, undefined, MOCK_DEFAULT_ORGANIZATION)
        logic = oauthAppsLogic()
        logic.mount()
    })

    it('loads OAuth apps on mount', async () => {
        await expectLogic(logic).toDispatchActions(['loadOAuthApps', 'loadOAuthAppsSuccess']).toMatchValues({
            oauthApps: MOCK_APPS,
            oauthAppsLoading: false,
        })
    })

    it('starts unresolved, so the page does not show the empty state before the first answer', () => {
        initKeaTests(true, undefined, undefined, MOCK_DEFAULT_ORGANIZATION)
        const freshLogic = oauthAppsLogic()
        freshLogic.mount()

        expect(freshLogic.values.oauthApps).toBeNull()
        expect(freshLogic.values.oauthAppsLoading).toEqual(true)
    })

    it('reports a failed load, and clears it when a retry succeeds', async () => {
        useMocks({ get: { '/api/organizations/:organization_id/oauth_applications/': () => [500, {}] } })
        logic.actions.loadOAuthApps()
        await expectLogic(logic).toDispatchActions(['loadOAuthAppsFailure']).toMatchValues({
            oauthApps: MOCK_APPS,
            oauthAppsLoadFailed: true,
        })

        useMocks({
            get: { '/api/organizations/:organization_id/oauth_applications/': { results: MOCK_APPS } },
        })
        logic.actions.loadOAuthApps()

        await expectLogic(logic).toDispatchActions(['loadOAuthAppsSuccess']).toMatchValues({
            oauthAppsLoadFailed: false,
        })
    })

    it.each([
        ['sent', 200, '', 'waiting_for_staff'],
        ['refused', 400, 'PostHog blocked provisioning for this application.', 'blocked'],
    ] as const)('a review note that is %s lands on the app or on the form', async (_name, code, formError, status) => {
        const sentNotes: unknown[] = []
        const answered = { ...MOCK_APPS[1], provisioning_status: 'changes_requested' as const }
        await expectLogic(logic).toDispatchActions(['loadOAuthAppsSuccess'])
        logic.actions.replaceOAuthApp(answered)
        useMocks({
            get: {
                '/api/organizations/:organization_id/oauth_applications/': {
                    results: [MOCK_APPS[0], { ...answered, provisioning_status: 'blocked' }],
                },
                '/api/organizations/:organization_id/oauth_applications/:id/': {
                    ...answered,
                    provisioning_status: 'blocked',
                },
            },
            post: {
                '/api/organizations/:organization_id/oauth_applications/:id/review_note/': async ({ request }) => {
                    sentNotes.push(await request.json())
                    return code === 200
                        ? [200, { ...answered, provisioning_status: 'waiting_for_staff' }]
                        : [400, { type: 'validation_error', attr: 'note', detail: formError }]
                },
            },
        })
        const pageLogic = oauthApplicationLogic({ id: answered.id })
        pageLogic.mount()
        await expectLogic(pageLogic).toDispatchActions(['loadApplicationSuccess'])
        pageLogic.actions.replaceApplication({ ...answered, registration: REGISTRATION })
        const noteLogic = oauthAppReviewNoteLogic({ appId: answered.id })
        noteLogic.mount()

        noteLogic.actions.setReviewNoteValue('note', 'We moved the document to our own domain.')
        noteLogic.actions.openNotePreview()
        expect(noteLogic.values.isNotePreviewOpen).toBe(true)
        await expectLogic(noteLogic, () => noteLogic.actions.submitReviewNote()).toFinishAllListeners()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(pageLogic).toFinishAllListeners()

        expect(sentNotes).toEqual([{ note: 'We moved the document to our own domain.' }])
        expect(noteLogic.values.isNotePreviewOpen).toBe(false)
        expect(logic.values.oauthApps?.[1].provisioning_status).toEqual(status)
        expect(pageLogic.values.application?.provisioning_status).toEqual(status)
        expect(noteLogic.values.reviewNoteManualErrors.note).toEqual(formError || undefined)
        expect(noteLogic.values.reviewNote.note).toEqual(formError ? 'We moved the document to our own domain.' : '')
    })

    it('does not preview an empty note', () => {
        const noteLogic = oauthAppReviewNoteLogic({ appId: MOCK_APPS[1].id })
        noteLogic.mount()

        noteLogic.actions.openNotePreview()

        expect(noteLogic.values.isNotePreviewOpen).toBe(false)
        expect(noteLogic.values.reviewNoteErrors.note).toEqual('Write a note for PostHog staff')
    })

    it.each([
        ['review', 'provisioning review', 'Waiting for PostHog staff'],
        ['verification', 'verify our OAuth application', "Our product's website:"],
    ] as const)('opens a %s request that any plan can send', async (request, opening, prompt) => {
        supportLogic.mount()
        const pageLogic = oauthApplicationLogic({ id: MOCK_APPS[1].id })
        pageLogic.mount()
        pageLogic.actions.replaceApplication({ ...MOCK_APPS[1], registration: REGISTRATION })

        pageLogic.actions.contactSupport(request)

        const form = supportLogic.values.sendSupportRequest
        expect(form.oauth_app_request).toBe(true)
        expect(form.message).toContain(opening)
        expect(form.message).toContain(MOCK_APPS[1].client_id)
        expect(form.message).toContain(prompt)
    })
})
