import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { parseManifestIntoState } from './customSourceManifest'
import { customSourceManifestBuilderLogic } from './customSourceManifestBuilderLogic'

const savedManifest = JSON.stringify({
    client: { base_url: 'https://saved.example.com', auth: { type: 'bearer' } },
    resources: [{ name: 'users', primary_key: 'id', endpoint: { path: '/users', data_selector: 'data' } }],
})

const pushedFields = (setValue: jest.Mock): Record<string, unknown> =>
    Object.fromEntries(setValue.mock.calls.map(([path, value]) => [(path as (string | number)[]).join('.'), value]))

describe('customSourceManifestBuilderLogic', () => {
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
    })

    describe('configuration page (initial manifest present)', () => {
        beforeEach(() => {
            logic = customSourceManifestBuilderLogic({ setValue, initialManifestJson: savedManifest })
            logic.mount()
        })

        it('parses the saved manifest into form state on mount', () => {
            expect(logic.values.hasContent).toBe(true)
            expect(logic.values.manifestState.base_url).toBe('https://saved.example.com')
            expect(logic.values.manifestState.streams[0].name).toBe('users')
        })

        it('mirrors the saved manifest into the outer form on mount', () => {
            expect(Object.keys(pushedFields(setValue))).toContain('payload.manifest_json')
        })
    })

    describe('manifest re-parse (the propsChanged path)', () => {
        beforeEach(() => {
            logic = customSourceManifestBuilderLogic({ setValue })
            logic.mount()
        })

        it('replaces form state and unblocks the outer-form sync', () => {
            expect(logic.values.manifestState.base_url).toBe('')

            logic.actions.setManifestState(parseManifestIntoState(savedManifest))

            expect(logic.values.manifestState.base_url).toBe('https://saved.example.com')
            expect(logic.values.hasContent).toBe(true)
            expect(Object.keys(pushedFields(setValue))).toContain('payload.manifest_json')
        })
    })

    describe('stream and header mutations', () => {
        beforeEach(() => {
            logic = customSourceManifestBuilderLogic({ setValue })
            logic.mount()
        })

        it('adds and removes streams', () => {
            expect(logic.values.manifestState.streams).toHaveLength(1)
            logic.actions.addStream()
            expect(logic.values.manifestState.streams).toHaveLength(2)
            logic.actions.removeStream(0)
            expect(logic.values.manifestState.streams).toHaveLength(1)
        })

        it('updates a stream paginator by index', () => {
            logic.actions.updatePaginator(0, { type: 'cursor', cursor_path: 'meta.next', cursor_param: 'after' })
            expect(logic.values.manifestState.streams[0].paginator).toEqual({
                type: 'cursor',
                cursor_path: 'meta.next',
                cursor_param: 'after',
            })
        })

        it('adds, edits, and removes headers', () => {
            logic.actions.addHeader()
            logic.actions.updateHeader(0, { key: 'X-Workspace', value: 'acme' })
            expect(logic.values.manifestState.headers).toEqual([{ key: 'X-Workspace', value: 'acme' }])
            logic.actions.removeHeader(0)
            expect(logic.values.manifestState.headers).toEqual([])
        })
    })
})
