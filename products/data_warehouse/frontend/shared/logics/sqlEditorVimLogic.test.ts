import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { UserUIConfiguration } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import { sqlEditorVimLogic } from './sqlEditorVimLogic'

describe('sqlEditorVimLogic', () => {
    let logic: ReturnType<typeof sqlEditorVimLogic.build>
    let patchedUser: Partial<UserType> | null

    function setUp({
        uiConfiguration,
        browserVimModeEnabled = false,
    }: {
        uiConfiguration: UserUIConfiguration | null
        browserVimModeEnabled?: boolean
    }): void {
        window.localStorage.setItem(
            'lib.logic.userPreferencesLogic.editorVimModeEnabled',
            JSON.stringify(browserVimModeEnabled)
        )
        initKeaTests()
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, ui_configuration: uiConfiguration })
        logic = sqlEditorVimLogic()
        logic.mount()
    }

    beforeEach(() => {
        patchedUser = null
        useMocks({
            patch: {
                '/api/users/@me/': async ({ request }) => {
                    patchedUser = (await request.json()) as Partial<UserType>
                    return [200, { ...MOCK_DEFAULT_USER, ...patchedUser }]
                },
            },
        })
    })

    afterEach(() => {
        logic.unmount()
        window.localStorage.clear()
    })

    it.each([
        ['nothing is saved to the account', null, true],
        ['the account has a vimrc but no Vim mode setting', { version: 1, sql_editor: { vimrc: 'set rnu' } }, true],
        ['the account turned Vim mode off', { version: 1, sql_editor: { vim_mode_enabled: false } }, false],
    ])('uses the browser setting only when %s', (_description, uiConfiguration, expected) => {
        setUp({ uiConfiguration, browserVimModeEnabled: true })

        expect(logic.values.vimModeEnabled).toBe(expected)
    })

    it('saves the vimrc without dropping the sidebar settings, then closes the modal', async () => {
        setUp({ uiConfiguration: { version: 1, sidebar: { items: { data: { visible: false } } } } })

        await expectLogic(logic, () => {
            logic.actions.openVimrcModal('first-editor')
            logic.actions.setVimrcDraft('inoremap jj <Esc>')
            logic.actions.saveVimrc()
        }).toFinishAllListeners()

        expect(patchedUser?.ui_configuration).toEqual({
            version: 1,
            sidebar: { items: { data: { visible: false } } },
            sql_editor: { vimrc: 'inoremap jj <Esc>' },
        })
        expect(logic.values.isVimrcModalOpen).toBe(false)
        expect(logic.values.vimrcSaving).toBe(false)
    })

    it('keeps menus and the vimrc modal owned by one editor', () => {
        setUp({ uiConfiguration: { version: 1 } })

        logic.actions.setEditorSettingsMenuOpen('first-editor', true)
        expect(logic.values.editorSettingsMenuKey).toBe('first-editor')

        logic.actions.setEditorSettingsMenuOpen('second-editor', true)
        logic.actions.setEditorSettingsMenuOpen('first-editor', false)
        expect(logic.values.editorSettingsMenuKey).toBe('second-editor')

        logic.actions.openVimrcModal('second-editor')
        expect(logic.values.editorSettingsMenuKey).toBeNull()
        expect(logic.values.vimrcEditorKey).toBe('second-editor')

        logic.actions.openVimrcModal('first-editor')
        expect(logic.values.vimrcEditorKey).toBe('first-editor')

        logic.actions.closeVimrcModal()
        expect(logic.values.isVimrcModalOpen).toBe(false)
        expect(logic.values.vimrcEditorKey).toBeNull()
    })

    it('keeps an in-flight Vim mode change when the vimrc is saved before it returns', async () => {
        const patches: Partial<UserType>[] = []
        let releaseFirstPatch: () => void = () => {}
        const firstPatchHeld = new Promise<void>((resolve) => {
            releaseFirstPatch = resolve
        })
        useMocks({
            patch: {
                '/api/users/@me/': async ({ request }) => {
                    const body = (await request.json()) as Partial<UserType>
                    patches.push(body)
                    if (patches.length === 1) {
                        await firstPatchHeld
                    }
                    return [200, { ...MOCK_DEFAULT_USER, ...body }]
                },
            },
        })
        setUp({ uiConfiguration: { version: 1 } })

        logic.actions.setVimModeEnabled(true)
        logic.actions.setVimrcDraft('set relativenumber')
        logic.actions.saveVimrc()
        await expectLogic(logic).toDispatchActions(['updateUserSuccess'])
        releaseFirstPatch()
        await expectLogic(logic).toDispatchActions(['updateUserSuccess'])

        expect(patches.map((patch) => patch.ui_configuration?.sql_editor)).toEqual([
            { vim_mode_enabled: true },
            { vim_mode_enabled: true, vimrc: 'set relativenumber' },
        ])
    })

    it('keeps an in-flight Vim mode change when an unrelated account update finishes first', async () => {
        let releaseVimPatch: () => void = () => {}
        const vimPatchHeld = new Promise<void>((resolve) => {
            releaseVimPatch = resolve
        })
        useMocks({
            patch: {
                '/api/users/@me/': async ({ request }) => {
                    const body = (await request.json()) as Partial<UserType>
                    if (body.ui_configuration) {
                        await vimPatchHeld
                    }
                    return [200, { ...MOCK_DEFAULT_USER, ...body }]
                },
            },
        })
        setUp({ uiConfiguration: { version: 1 } })

        logic.actions.setVimModeEnabled(true)
        userLogic.actions.updateUser({ theme_mode: 'dark' })
        await expectLogic(logic).toDispatchActions(['updateUserSuccess'])

        expect(logic.values.vimModeEnabled).toBe(true)
        releaseVimPatch()
    })
})
