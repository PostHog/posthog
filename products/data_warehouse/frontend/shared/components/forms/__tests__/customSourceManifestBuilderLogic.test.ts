import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'

import { externalDataSourcesDraftCustomManifestCreate } from 'products/warehouse_sources/frontend/generated/api'

import { parseManifestIntoState } from '../customSourceManifest'
import { customSourceManifestBuilderLogic } from '../customSourceManifestBuilderLogic'

jest.mock('lib/lemon-ui/LemonToast', () => ({
    lemonToast: { success: jest.fn(), warning: jest.fn(), error: jest.fn() },
}))
jest.mock('products/warehouse_sources/frontend/generated/api', () => ({
    externalDataSourcesDraftCustomManifestCreate: jest.fn(),
}))

const mockDraft = externalDataSourcesDraftCustomManifestCreate as jest.Mock

const savedManifest = JSON.stringify({
    client: { base_url: 'https://saved.example.com', auth: { type: 'bearer' } },
    resources: [{ name: 'users', primary_key: 'id', endpoint: { path: '/users', data_selector: 'data' } }],
})

const pushedFields = (setValue: jest.Mock): Record<string, unknown> =>
    Object.fromEntries(setValue.mock.calls.map(([path, value]) => [(path as (string | number)[]).join('.'), value]))

describe('customSourceManifestBuilderLogic', () => {
    // Safety net for tests that call silenceKeaLoadersErrors() inline
    afterEach(resumeKeaLoadersErrors)

    let logic: ReturnType<typeof customSourceManifestBuilderLogic.build>
    let setValue: jest.Mock

    beforeEach(() => {
        initKeaTests()
        setValue = jest.fn()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('wizard mode (no initial manifest)', () => {
        beforeEach(() => {
            logic = customSourceManifestBuilderLogic({ setValue })
            logic.mount()
        })

        it('does not touch the outer form before the user edits', () => {
            expect(setValue).not.toHaveBeenCalled()
            expect(logic.values.hasContent).toBe(false)
        })

        it('pushes the manifest and secret fields once the user edits', async () => {
            await expectLogic(logic, () => {
                logic.actions.updateState({ base_url: 'https://api.example.com' })
            })
                .toDispatchActions(['updateState'])
                .toMatchValues({ hasContent: true })

            const pushed = pushedFields(setValue)
            expect(JSON.parse(pushed['payload.manifest_json'] as string).client.base_url).toBe(
                'https://api.example.com'
            )
            expect(pushed['payload.auth_token']).toBe('')
            expect(pushed['payload.auth_api_key']).toBe('')
            expect(pushed['payload.auth_password']).toBe('')
        })

        it('routes a bearer token to the secret field, never into the manifest', () => {
            logic.actions.updateState({ auth_type: 'bearer', auth_token: 'tok_secret' })

            const pushed = pushedFields(setValue)
            expect(pushed['payload.auth_token']).toBe('tok_secret')
            expect(pushed['payload.manifest_json']).not.toContain('tok_secret')
        })

        it('clears the bearer token in the outer form after switching auth away from bearer', () => {
            logic.actions.updateState({ auth_type: 'bearer', auth_token: 'tok_secret' })
            expect(pushedFields(setValue)['payload.auth_token']).toBe('tok_secret')

            logic.actions.updateState({ auth_type: 'api_key' })
            expect(pushedFields(setValue)['payload.auth_token']).toBe('')
        })
    })

    describe('configuration page (initial manifest present)', () => {
        beforeEach(() => {
            logic = customSourceManifestBuilderLogic({ setValue, initialManifestJson: savedManifest })
            logic.mount()
        })

        it('parses the saved manifest into form state on mount', () => {
            expect(logic.values.hasContent).toBe(true)
            expect(logic.values.manifestState.base_url).toBe('https://saved.example.com')
            expect(logic.values.manifestState.tables[0].name).toBe('users')
        })

        it('opens directly in the builder, never the AI intro, when a manifest already exists', () => {
            expect(logic.values.showBuilder).toBe(true)
        })

        it('mirrors the saved manifest into the outer form on mount', () => {
            const pushed = pushedFields(setValue)
            expect(JSON.parse(pushed['payload.manifest_json'] as string).client.base_url).toBe(
                'https://saved.example.com'
            )
        })
    })

    describe('manifest re-parse (the propsChanged path)', () => {
        beforeEach(() => {
            logic = customSourceManifestBuilderLogic({ setValue })
            logic.mount()
        })

        it('replaces form state and unblocks the outer-form sync', () => {
            expect(logic.values.manifestState.base_url).toBe('')
            // A fresh source (no manifest yet) starts on the AI intro, not the builder.
            expect(logic.values.showBuilder).toBe(false)

            logic.actions.setManifestState(parseManifestIntoState(savedManifest))

            expect(logic.values.manifestState.base_url).toBe('https://saved.example.com')
            expect(logic.values.hasContent).toBe(true)
            expect(Object.keys(pushedFields(setValue))).toContain('payload.manifest_json')
        })

        it('does not clobber in-progress user edits when initialManifestJson arrives late', () => {
            // User types something before the job_inputs poll lands.
            logic.actions.updateState({ base_url: 'https://user-typed.example.com' })
            expect(logic.values.userHasEdited).toBe(true)

            // Poll lands — the props update should be ignored because the user has edits.
            customSourceManifestBuilderLogic({ setValue, initialManifestJson: savedManifest })

            expect(logic.values.manifestState.base_url).toBe('https://user-typed.example.com')
        })

        it('hydrates from a late-arriving initialManifestJson when the user has not edited yet', () => {
            expect(logic.values.userHasEdited).toBe(false)
            customSourceManifestBuilderLogic({ setValue, initialManifestJson: savedManifest })

            expect(logic.values.manifestState.base_url).toBe('https://saved.example.com')
            // The late manifest also moves the user off the AI intro into the builder.
            expect(logic.values.showBuilder).toBe(true)
        })
    })

    describe('table and header mutations', () => {
        beforeEach(() => {
            logic = customSourceManifestBuilderLogic({ setValue })
            logic.mount()
        })

        it('adds and removes tables', () => {
            expect(logic.values.manifestState.tables).toHaveLength(1)
            logic.actions.addTable()
            expect(logic.values.manifestState.tables).toHaveLength(2)
            logic.actions.removeTable(0)
            expect(logic.values.manifestState.tables).toHaveLength(1)
        })

        it('cascades a parent rename to dependent tables through the reducer', () => {
            // The cascade behavior itself is unit-tested on the pure helpers;
            // this pins that the reducer is actually wired to them.
            logic.actions.updateTable(0, { name: 'forms' })
            logic.actions.addTable()
            logic.actions.updateTable(1, { name: 'responses', parent_table: 'forms' })

            logic.actions.updateTable(0, { name: 'surveys' })
            expect(logic.values.manifestState.tables[1].parent_table).toBe('surveys')

            logic.actions.removeTable(0)
            expect(logic.values.manifestState.tables[0].parent_table).toBe('')
        })

        it('updates a table paginator by index', () => {
            logic.actions.updatePaginator(0, { type: 'cursor', cursor_path: 'meta.next', cursor_param: 'after' })
            expect(logic.values.manifestState.tables[0].paginator).toEqual({
                type: 'cursor',
                cursor_path: 'meta.next',
                cursor_param: 'after',
            })
        })

        it('adds, edits, and removes headers', () => {
            logic.actions.addHeader()
            logic.actions.updateHeader(0, { key: 'X-Workspace', value: 'acme' })
            expect(logic.values.manifestState.headers).toMatchObject([{ key: 'X-Workspace', value: 'acme' }])
            expect(logic.values.manifestState.headers[0].id).toBeTruthy()
            logic.actions.removeHeader(0)
            expect(logic.values.manifestState.headers).toEqual([])
        })
    })

    describe('AI draft from docs (generateFromDocs)', () => {
        beforeEach(() => {
            mockDraft.mockReset()
            ;(lemonToast.success as jest.Mock).mockClear()
            ;(lemonToast.warning as jest.Mock).mockClear()
            ;(lemonToast.error as jest.Mock).mockClear()
            logic = customSourceManifestBuilderLogic({ setValue })
            logic.mount()
        })

        it('rejects an empty docs URL without calling the backend', async () => {
            await expectLogic(logic, () => {
                logic.actions.generateFromDocs()
            }).toDispatchActions(['generateFromDocsSuccess'])

            expect(mockDraft).not.toHaveBeenCalled()
            expect(lemonToast.error).toHaveBeenCalledWith('Enter a documentation URL first')
            expect(logic.values.showBuilder).toBe(false)
        })

        it('populates the builder and confirms on a validated draft', async () => {
            mockDraft.mockResolvedValue({
                draft_status: 'ok',
                manifest_json: savedManifest,
                resource_names: ['users'],
                attempts: 1,
                error: null,
            })
            logic.actions.setDocsUrl('https://docs.example.com')

            await expectLogic(logic, () => {
                logic.actions.generateFromDocs()
            }).toDispatchActions(['generateFromDocsSuccess', 'setShowBuilder'])

            expect(logic.values.manifestState.base_url).toBe('https://saved.example.com')
            expect(logic.values.showBuilder).toBe(true)
            expect(lemonToast.success).toHaveBeenCalled()
        })

        it('still opens the draft for hand-editing when it did not fully validate', async () => {
            // The repair-loop fix means an `invalid` result can still carry a manifest to hand off.
            mockDraft.mockResolvedValue({
                draft_status: 'invalid',
                manifest_json: savedManifest,
                resource_names: [],
                attempts: 4,
                error: 'resources: must not be empty',
            })
            logic.actions.setDocsUrl('https://docs.example.com')

            await expectLogic(logic, () => {
                logic.actions.generateFromDocs()
            }).toDispatchActions(['generateFromDocsSuccess', 'setShowBuilder'])

            expect(logic.values.showBuilder).toBe(true)
            expect(lemonToast.warning).toHaveBeenCalledWith('resources: must not be empty')
        })

        it.each([
            ['429 throttle detail', 429, { detail: 'Request was throttled. Expected available in 30 seconds.' }],
            ['400 error message', 400, { message: 'Could not fetch the docs URL.' }],
        ] as [string, number, Record<string, string>][])(
            'toasts the backend reason (%s) and resolves without a loader failure',
            async (_label, status, data) => {
                mockDraft.mockRejectedValue(new ApiError('failed', status, undefined, data))
                logic.actions.setDocsUrl('https://docs.example.com')

                // A handled API error is caught in the loader so it never becomes a kea-loaders
                // failure — otherwise the global onFailure would capture an exception for an
                // expected, user-facing input error, leaking into error tracking as noise.
                await expectLogic(logic, () => {
                    logic.actions.generateFromDocs()
                })
                    .toDispatchActions(['generateFromDocsSuccess'])
                    .toNotHaveDispatchedActions(['generateFromDocsFailure'])

                expect(lemonToast.error).toHaveBeenCalledWith(data.detail ?? data.message)
            }
        )

        it('captures unexpected non-ApiError failures instead of swallowing them', async () => {
            // A non-ApiError throw is a genuine bug, so it must still route through the loader
            // failure path (where the global onFailure captures it) — only handled ApiErrors are
            // suppressed.
            silenceKeaLoadersErrors()
            mockDraft.mockRejectedValue(new TypeError('unexpected'))
            logic.actions.setDocsUrl('https://docs.example.com')

            await expectLogic(logic, () => {
                logic.actions.generateFromDocs()
            }).toDispatchActions(['generateFromDocsFailure'])

            expect(lemonToast.error).toHaveBeenCalledWith(
                'Failed to draft a manifest. Try again, or configure it manually.'
            )
        })
    })
})
