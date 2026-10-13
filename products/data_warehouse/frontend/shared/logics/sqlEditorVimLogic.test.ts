import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { uiCustomizationLogic } from '~/layout/uiCustomizationLogic'
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

    it.each(['vimrc', 'sidebar-after-vim', 'sidebar-before-vim'] as const)(
        'preserves both settings when the queued change is %s',
        async (scenario) => {
            const patches: Partial<UserType>[] = []
            let releaseFirstPatch: () => void = () => {}
            let reportFirstStarted: () => void = () => {}
            const firstStarted = new Promise<void>((resolve) => {
                reportFirstStarted = resolve
            })
            const firstPatchHeld = new Promise<void>((resolve) => {
                releaseFirstPatch = resolve
            })
            useMocks({
                patch: {
                    '/api/users/@me/': async ({ request }) => {
                        const body = (await request.json()) as Partial<UserType>
                        patches.push(body)
                        if (patches.length === 1) {
                            reportFirstStarted()
                            await firstPatchHeld
                        }
                        return [200, { ...MOCK_DEFAULT_USER, ...body }]
                    },
                },
            })
            setUp({ uiConfiguration: { version: 1 } })

            if (scenario === 'sidebar-before-vim') {
                uiCustomizationLogic.actions.setSidebarDensity('compact')
            } else {
                logic.actions.setVimModeEnabled(true)
            }
            await firstStarted

            if (scenario === 'vimrc') {
                logic.actions.setVimrcDraft('set relativenumber')
                logic.actions.saveVimrc()
            } else if (scenario === 'sidebar-after-vim') {
                uiCustomizationLogic.actions.setSidebarDensity('compact')
            } else {
                logic.actions.setVimModeEnabled(true)
            }
            const requestsBeforeRelease = patches.length
            const optimisticConfiguration = logic.values.uiConfiguration
            await expectLogic(userLogic, releaseFirstPatch).toFinishAllListeners()

            const expectedConfiguration = {
                version: 1,
                ...(scenario === 'vimrc' ? {} : { sidebar: { density: 'compact' } }),
                sql_editor: {
                    vim_mode_enabled: true,
                    ...(scenario === 'vimrc' ? { vimrc: 'set relativenumber' } : {}),
                },
            }
            expect(requestsBeforeRelease).toBe(1)
            expect(patches).toHaveLength(2)
            expect(optimisticConfiguration).toEqual(expectedConfiguration)
            expect(patches[1].ui_configuration).toEqual(expectedConfiguration)
            expect(logic.values.uiConfiguration).toEqual(expectedConfiguration)
        }
    )

    it.each([200, 400])('keeps queued Vim changes when an unrelated update returns %s', async (status) => {
        let releaseAccountPatch: () => void = () => {}
        let reportAccountStarted: () => void = () => {}
        let releaseVimPatch: () => void = () => {}
        let reportVimStarted: () => void = () => {}
        const accountStarted = new Promise<void>((resolve) => {
            reportAccountStarted = resolve
        })
        const accountPatchHeld = new Promise<void>((resolve) => {
            releaseAccountPatch = resolve
        })
        const vimStarted = new Promise<void>((resolve) => {
            reportVimStarted = resolve
        })
        const vimPatchHeld = new Promise<void>((resolve) => {
            releaseVimPatch = resolve
        })
        useMocks({
            patch: {
                '/api/users/@me/': async ({ request }) => {
                    const body = (await request.json()) as Partial<UserType>
                    if (!body.ui_configuration) {
                        reportAccountStarted()
                        await accountPatchHeld
                        return status === 400
                            ? [400, { detail: 'Update rejected by server.' }]
                            : [200, { ...MOCK_DEFAULT_USER, ...body }]
                    }
                    if (!body.ui_configuration.sql_editor?.vimrc) {
                        reportVimStarted()
                        await vimPatchHeld
                    }
                    return [200, { ...MOCK_DEFAULT_USER, ...body }]
                },
            },
        })
        setUp({ uiConfiguration: { version: 1 } })
        silenceKeaLoadersErrors()
        try {
            userLogic.actions.updateUser({ theme_mode: 'dark' })
            await accountStarted
            logic.actions.setVimModeEnabled(true)
            logic.actions.setVimrcDraft('set relativenumber')
            logic.actions.saveVimrc()

            const accountFinished = expectLogic(userLogic).toDispatchActions([
                status === 400 ? 'updateUserFailure' : 'updateUserSuccess',
            ])
            releaseAccountPatch()
            await accountFinished
            await vimStarted

            expect(logic.values.vimModeEnabled).toBe(true)
            expect(logic.values.vimrc).toBe('set relativenumber')
            expect(logic.values.vimrcSaving).toBe(true)

            await expectLogic(userLogic, releaseVimPatch).toFinishAllListeners()
            expect(logic.values.vimrcSaving).toBe(false)
            expect(logic.values.vimrc).toBe('set relativenumber')
        } finally {
            releaseAccountPatch()
            releaseVimPatch()
            resumeKeaLoadersErrors()
        }
    })

    it('clears the loading state only when its own vimrc save fails', async () => {
        useMocks({ patch: { '/api/users/@me/': [400, { detail: 'Update rejected by server.' }] } })
        setUp({ uiConfiguration: { version: 1, sql_editor: { vimrc: 'set pcre' } } })
        silenceKeaLoadersErrors()
        try {
            await expectLogic(userLogic, () => {
                logic.actions.openVimrcModal('first-editor')
                logic.actions.setVimrcDraft('set relativenumber')
                logic.actions.saveVimrc()
            }).toDispatchActions(['updateUserFailure'])

            expect(logic.values.vimrcSaving).toBe(false)
            expect(logic.values.isVimrcModalOpen).toBe(true)
            expect(logic.values.vimrc).toBe('set pcre')
        } finally {
            resumeKeaLoadersErrors()
        }
    })
})
