import { act, fireEvent, waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { openRevokeKeyDialog, openRollKeyDialog } from './organizationPersonalAPIKeyDialogs'
import { organizationPersonalAPIKeysLogic } from './organizationPersonalAPIKeysLogic'

const MOCK_KEYS = [
    {
        id: 'key-ada',
        owner: { first_name: 'Ada', last_name: 'Lovelace', email: 'ada@x.com' },
        mask_value: 'phx_***1234',
        scopes: ['insight:read'],
        access_scope: { type: 'all' },
        reaches_other_organizations: true,
        last_used_at: null,
        created_at: '2026-01-01T00:00:00Z',
    },
    {
        id: 'key-alan',
        owner: { first_name: 'Alan', last_name: 'Turing', email: 'alan@x.com' },
        mask_value: 'phx_***5678',
        scopes: ['feature_flag:write'],
        access_scope: { type: 'projects', projects: [{ id: 1, name: 'Default project' }] },
        reaches_other_organizations: false,
        last_used_at: '2026-02-01T00:00:00Z',
        created_at: '2026-01-15T00:00:00Z',
    },
]

describe('organizationPersonalAPIKeysLogic', () => {
    let logic: ReturnType<typeof organizationPersonalAPIKeysLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/organizations/:organization_id/personal_api_keys/': {
                    count: MOCK_KEYS.length,
                    next: null,
                    previous: null,
                    results: MOCK_KEYS,
                },
            },
        })
        initKeaTests()
        logic = organizationPersonalAPIKeysLogic()
        logic.mount()
    })

    it('loads keys on mount', async () => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation()
        await expectLogic(logic).toDispatchActions(['loadKeys', 'loadKeysSuccess']).toMatchValues({
            keys: MOCK_KEYS,
            keysLoading: false,
        })

        logic.actions.loadKeys()
        await expectLogic(logic).toDispatchActions(['loadKeysSuccess'])
        const views = capture.mock.calls.filter(([event]) => event === 'organization personal api keys viewed')
        expect(views).toEqual([['organization personal api keys viewed', { key_count: MOCK_KEYS.length }]])
    })

    it.each(['roll', 'revoke'] as const)('submits %s only once during dialog close', async (action) => {
        const request = jest.fn(() => [200, { outcome: action === 'roll' ? 'rolled' : 'deleted' }])
        useMocks({
            post: { [`/api/organizations/:organization_id/personal_api_keys/key-ada/${action}/`]: request },
        })
        await expectLogic(logic).toFinishAllListeners()

        act(() => {
            const openDialog = action === 'roll' ? openRollKeyDialog : openRevokeKeyDialog
            openDialog(logic.values.keys[0], 'Ada', () => {
                if (action === 'roll') {
                    logic.actions.rollKey('key-ada')
                } else {
                    logic.actions.revokeKey('key-ada')
                }
            })
        })
        const button = document.querySelector(`[data-attr="organization-personal-api-key-${action}-confirm"]`)!
        fireEvent.click(button)
        fireEvent.click(button)

        await expectLogic(logic).toFinishAllListeners()
        expect(request).toHaveBeenCalledTimes(1)
        await waitFor(() => expect(document.body.contains(button)).toBe(false))
    })

    it('starts with empty array and loading state', () => {
        expect(logic.values.keys).toEqual([])
        expect(logic.values.keysLoading).toEqual(true)
    })

    it('filters by owner name, email, or scope', async () => {
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setSearch('lovelace')
        expect(logic.values.filteredKeys).toEqual([MOCK_KEYS[0]])

        logic.actions.setSearch('alan@x.com')
        expect(logic.values.filteredKeys).toEqual([MOCK_KEYS[1]])

        logic.actions.setSearch('feature_flag')
        expect(logic.values.filteredKeys).toEqual([MOCK_KEYS[1]])

        logic.actions.setSearch('  ')
        expect(logic.values.filteredKeys).toEqual(MOCK_KEYS)

        logic.actions.setSearch('nomatch')
        expect(logic.values.filteredKeys).toEqual([])
    })

    it.each([
        {
            name: 'roll one key',
            run: () => logic.actions.rollKey('key-ada'),
            inFlight: 'key-ada',
            path: '/api/organizations/:organization_id/personal_api_keys/key-ada/roll/',
            response: [200, { outcome: 'rolled' }],
            finish: 'keyActionSuccess',
            toast: { kind: 'success', text: /^Rolled 1\skey$/ },
            event: [
                'organization personal api key action completed',
                { action: 'roll', target: 'single', rolled: 1, deleted: 0 },
            ],
        },
        {
            name: 'revoke a shared key',
            run: () => logic.actions.revokeKey('key-ada'),
            inFlight: 'key-ada',
            path: '/api/organizations/:organization_id/personal_api_keys/key-ada/revoke/',
            response: [200, { outcome: 'deleted' }],
            finish: 'keyActionSuccess',
            toast: { kind: 'success', text: /^Revoked 1\skey$/ },
            event: [
                'organization personal api key action completed',
                { action: 'revoke', target: 'single', rolled: 0, deleted: 1 },
            ],
        },
        {
            name: 'revoke one key that no longer reaches this organization',
            run: () => logic.actions.revokeKey('key-alan'),
            inFlight: 'key-alan',
            path: '/api/organizations/:organization_id/personal_api_keys/key-alan/revoke/',
            response: [404, { detail: 'Not found.' }],
            finish: 'keyActionFailure',
            toast: {
                kind: 'error',
                text: /may have been deleted or no longer have access to this organization/,
            },
            event: ['organization personal api key action failed', { action: 'revoke', target: 'single', status: 404 }],
        },
    ])(
        'marks the action in flight and reloads after it: $name',
        async ({ run, inFlight, path, response, finish, toast, event }) => {
            const toastSpy = jest.spyOn(lemonToast, toast.kind as 'success' | 'error').mockImplementation()
            const capture = jest.spyOn(posthog, 'capture').mockImplementation()
            await expectLogic(logic).toFinishAllListeners()

            let release: () => void = () => {}
            const requestHeld = new Promise<void>((resolve) => {
                release = resolve
            })
            useMocks({
                post: {
                    [path]: async () => {
                        await requestHeld
                        return response
                    },
                },
            })

            run()
            expect(logic.values.keyActionInFlight).toEqual(inFlight)

            release()
            await expectLogic(logic).toDispatchActions([finish, 'loadKeys', 'loadKeysSuccess']).toMatchValues({
                keyActionInFlight: null,
            })
            expect(toastSpy.mock.calls[0][0]).toMatch(toast.text)
            expect(capture).toHaveBeenCalledWith(...event)
        }
    )
})
