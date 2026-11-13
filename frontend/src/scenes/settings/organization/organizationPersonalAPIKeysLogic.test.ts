import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { act, fireEvent, waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    openRevokeAllKeysDialog,
    openRollAllKeysDialog,
    openRevokeKeyDialog,
    openRollKeyDialog,
} from './organizationPersonalAPIKeyDialogs'
import { organizationPersonalAPIKeysLogic } from './organizationPersonalAPIKeysLogic'

const BULK_RESULT = { rolled: 0, deleted: 0, skipped: 0, failed: 0, started_at: '2026-03-01T14:05:00Z' }

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
    {
        id: 'key-mine',
        owner: { first_name: 'John', last_name: 'Doe', email: MOCK_DEFAULT_USER.email },
        mask_value: 'phx_***9012',
        scopes: ['*'],
        access_scope: { type: 'organization' },
        reaches_other_organizations: false,
        last_used_at: null,
        created_at: '2026-01-20T00:00:00Z',
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

    it.each(['roll', 'revoke', 'roll_all', 'revoke_all'] as const)(
        'submits %s only once during dialog close',
        async (action) => {
            const bulk = action.endsWith('_all')
            const roll = action.startsWith('roll')
            const request = jest.fn(() => [
                200,
                bulk
                    ? { ...BULK_RESULT, rolled: roll ? 2 : 0, deleted: roll ? 0 : 2 }
                    : { outcome: roll ? 'rolled' : 'deleted' },
            ])
            useMocks({
                post: {
                    [`/api/organizations/:organization_id/personal_api_keys/${bulk ? '' : 'key-ada/'}${action}/`]:
                        request,
                },
            })
            await expectLogic(logic).toFinishAllListeners()

            act(() => {
                if (bulk) {
                    if (roll) {
                        openRollAllKeysDialog(logic.values.bulkSummary, '', null, () => logic.actions.rollAllKeys())
                    } else {
                        openRevokeAllKeysDialog(logic.values.bulkSummary, '', () => logic.actions.revokeAllKeys())
                    }
                } else {
                    const openDialog = roll ? openRollKeyDialog : openRevokeKeyDialog
                    openDialog(logic.values.keys[0], 'Ada', () => {
                        if (roll) {
                            logic.actions.rollKey('key-ada')
                        } else {
                            logic.actions.revokeKey('key-ada')
                        }
                    })
                }
            })
            if (bulk) {
                fireEvent.change(document.querySelector('input')!, {
                    target: { value: `${roll ? 'roll' : 'revoke'} all keys` },
                })
            }
            const button = document.querySelector(
                bulk ? 'button[type="submit"]' : `[data-attr="organization-personal-api-key-${action}-confirm"]`
            )!
            await waitFor(() => expect(button.hasAttribute('disabled')).toBe(false))
            fireEvent.click(button)
            fireEvent.click(button)

            await waitFor(() => expect(request).toHaveBeenCalled())
            await expectLogic(logic).toFinishAllListeners()
            expect(request).toHaveBeenCalledTimes(1)
            await waitFor(() => expect(document.body.contains(button)).toBe(false))
        }
    )

    it.each(['roll_all', 'revoke_all'] as const)('blocks %s while the typed phrase does not match', async (action) => {
        const request = jest.fn(() => [200, BULK_RESULT])
        useMocks({ post: { [`/api/organizations/:organization_id/personal_api_keys/${action}/`]: request } })
        await expectLogic(logic).toFinishAllListeners()

        act(() => {
            if (action === 'roll_all') {
                openRollAllKeysDialog(logic.values.bulkSummary, '', null, () => logic.actions.rollAllKeys())
            } else {
                openRevokeAllKeysDialog(logic.values.bulkSummary, '', () => logic.actions.revokeAllKeys())
            }
        })
        fireEvent.change(document.querySelector('input')!, { target: { value: 'roll some keys' } })
        fireEvent.click(document.querySelector('button[type="submit"]')!)

        await waitFor(() => expect(document.body.textContent).toContain('The text does not match.'))
        await expectLogic(logic).toFinishAllListeners()
        expect(request).not.toHaveBeenCalled()
    })

    it('retries a roll of all keys without rolling the keys it already rolled', async () => {
        const successToast = jest.spyOn(lemonToast, 'success').mockImplementation()
        jest.spyOn(lemonToast, 'warning').mockImplementation()
        await expectLogic(logic).toFinishAllListeners()
        const bodies: unknown[] = []
        const responses = [
            { ...BULK_RESULT, rolled: 2, failed: 1 },
            { ...BULK_RESULT, rolled: 1, skipped: 2 },
        ]
        useMocks({
            post: {
                '/api/organizations/:organization_id/personal_api_keys/roll_all/': async ({ request }) => {
                    bodies.push(await request.json())
                    return [200, responses[bodies.length - 1]]
                },
            },
        })

        logic.actions.rollAllKeys()
        await expectLogic(logic)
            .toDispatchActions(['keyActionSuccess'])
            .toMatchValues({ rollAllRetrySince: BULK_RESULT.started_at })
        logic.actions.rollAllKeys()
        await expectLogic(logic).toDispatchActions(['keyActionSuccess']).toMatchValues({ rollAllRetrySince: null })

        expect(bodies).toEqual([{ skip_rolled_since: null }, { skip_rolled_since: BULK_RESULT.started_at }])
        expect(successToast.mock.calls[0][0]).toMatch(
            /^Rolled 1\skey\. Skipped 2\skeys rolled since your first attempt at .+, so their new secrets keep working\.$/
        )
    })

    it('keeps no retry cutoff when a roll of all keys gets no response', async () => {
        jest.spyOn(lemonToast, 'error').mockImplementation()
        await expectLogic(logic).toFinishAllListeners()
        useMocks({
            post: {
                '/api/organizations/:organization_id/personal_api_keys/roll_all/': () => [
                    500,
                    { detail: 'A server error occurred.' },
                ],
            },
        })

        logic.actions.rollAllKeys()

        await expectLogic(logic).toDispatchActions(['keyActionFailure']).toMatchValues({ rollAllRetrySince: null })
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

    it('summarizes keys for the bulk dialogs', async () => {
        await expectLogic(logic).toFinishAllListeners()

        // A bulk action changes every key, so the search box must not narrow the summary.
        logic.actions.setSearch('lovelace')
        expect(logic.values.bulkSummary).toEqual({ total: 3, alsoInOtherOrganizations: 1, ownedByMe: 1 })
    })

    it.each([
        {
            name: 'roll all keys',
            run: () => logic.actions.rollAllKeys(),
            inFlight: 'all',
            path: '/api/organizations/:organization_id/personal_api_keys/roll_all/',
            response: [200, { ...BULK_RESULT, rolled: 3 }],
            finish: 'keyActionSuccess',
            toast: { kind: 'success', text: /^Rolled 3\skeys$/ },
            event: [
                'organization personal api key action completed',
                { action: 'roll', target: 'all', rolled: 3, deleted: 0, skipped: 0, failed: 0 },
            ],
        },
        {
            name: 'revoke all keys',
            run: () => logic.actions.revokeAllKeys(),
            inFlight: 'all',
            path: '/api/organizations/:organization_id/personal_api_keys/revoke_all/',
            response: [200, { ...BULK_RESULT, deleted: 3 }],
            finish: 'keyActionSuccess',
            toast: { kind: 'success', text: /^Revoked 3\skeys$/ },
            event: [
                'organization personal api key action completed',
                { action: 'revoke', target: 'all', rolled: 0, deleted: 3, skipped: 0, failed: 0 },
            ],
        },
        {
            name: 'roll all keys that leaves some keys unchanged',
            run: () => logic.actions.rollAllKeys(),
            inFlight: 'all',
            path: '/api/organizations/:organization_id/personal_api_keys/roll_all/',
            response: [200, { ...BULK_RESULT, rolled: 2, failed: 1 }],
            finish: 'keyActionSuccess',
            toast: { kind: 'warning', text: /^Rolled 2\skeys\. Couldn't change 1\skey\. Try again to change it\.$/ },
            event: [
                'organization personal api key action completed',
                { action: 'roll', target: 'all', rolled: 2, deleted: 0, skipped: 0, failed: 1 },
            ],
        },
        {
            name: 'revoke all keys that fails partway',
            run: () => logic.actions.revokeAllKeys(),
            inFlight: 'all',
            path: '/api/organizations/:organization_id/personal_api_keys/revoke_all/',
            response: [500, { detail: 'A server error occurred.' }],
            finish: 'keyActionFailure',
            toast: { kind: 'error', text: /Some keys may already have changed/ },
            event: ['organization personal api key action failed', { action: 'revoke', target: 'all', status: 500 }],
        },
        {
            name: 'roll all keys that a permission check rejects',
            run: () => logic.actions.rollAllKeys(),
            inFlight: 'all',
            path: '/api/organizations/:organization_id/personal_api_keys/roll_all/',
            response: [403, { detail: 'You do not have permission to perform this action.' }],
            finish: 'keyActionFailure',
            toast: {
                kind: 'error',
                text: /^Couldn't roll all keys\. You do not have permission to perform this action\.$/,
            },
            event: ['organization personal api key action failed', { action: 'roll', target: 'all', status: 403 }],
        },
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
                { action: 'roll', target: 'single', rolled: 1, deleted: 0, skipped: 0, failed: 0 },
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
                { action: 'revoke', target: 'single', rolled: 0, deleted: 1, skipped: 0, failed: 0 },
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
            const toastSpy = jest.spyOn(lemonToast, toast.kind as 'success' | 'warning' | 'error').mockImplementation()
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
