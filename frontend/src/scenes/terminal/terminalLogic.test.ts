import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { waitFor } from '@testing-library/react'
import { router } from 'kea-router'

import { commandLogic } from 'lib/components/Command/commandLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { FILES_TREE_KEY } from '~/layout/panel-layout/navbar/tabs/navFilesTabLogic'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { initKeaTests } from '~/test/init'

import { ModalTerminalRuntime } from './ModalTerminalRuntime'
import { PosthogFilesystem } from './posthogFilesystem'
import { TerminalConfirmation } from './terminalConfirmation'
import { terminalDockLogic } from './terminalDockLogic'
import { terminalLogic } from './terminalLogic'
import { TerminalRuntime } from './terminalRuntime'

const mockFolderFor = jest.fn<Promise<string | null>, []>()

jest.mock('./terminalRuntime', () => ({
    TerminalRuntime: jest.fn().mockImplementation(() => ({
        start: jest.fn(async (_server, _signal, ready) => ready()),
        write: jest.fn(),
        displayInput: { release: jest.fn() },
        dispose: jest.fn(),
        resize: jest.fn(),
        syncClock: jest.fn(),
        changeDirectory: jest.fn(() => true),
        read: jest.fn(() => ''),
    })),
}))
jest.mock('./ModalTerminalRuntime', () => ({
    ModalTerminalRuntime: jest.fn().mockImplementation(() => ({
        start: jest.fn(async (size) => size),
        stop: jest.fn(async () => {}),
        write: jest.fn(),
        resize: jest.fn(),
        read: jest.fn(() => ''),
    })),
}))
jest.mock('./TerminalSession', () => ({
    TerminalSession: jest.fn().mockImplementation(() => ({
        attach: jest.fn(),
        detach: jest.fn(),
        dispose: jest.fn(),
        view: { clear: jest.fn(), write: jest.fn(), cols: 80, rows: 24, focus: jest.fn() },
    })),
}))
jest.mock('./posthogFilesystem', () => ({
    PosthogFilesystem: jest.fn().mockImplementation(() => ({
        load: jest.fn(async () => {}),
        folderFor: mockFolderFor,
        folderPath: (path: string) => '/posthog/files/' + path,
    })),
}))
jest.mock('./posthogCommands', () => ({ PosthogCommands: jest.fn() }))
jest.mock('./terminalAI', () => ({ TerminalAI: jest.fn() }))

describe('terminal lifecycle', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        mockFolderFor.mockReset().mockResolvedValue(null)
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.POSTHOG_TERMINAL]: true })
        breadcrumbsLogic.mount()
        jest.spyOn(breadcrumbsLogic.selectors, 'projectTreeRef').mockReturnValue(null)
        terminalLogic.mount()
    })

    afterEach(() => jest.restoreAllMocks())

    it('starts the selected Modal size and prevents a new session until Stop finishes', async () => {
        terminalLogic.actions.attach(document.createElement('div'))
        expect(terminalLogic.values.status).toBe('idle')
        expect(TerminalRuntime).not.toHaveBeenCalled()
        expect(ModalTerminalRuntime).not.toHaveBeenCalled()
        terminalLogic.actions.setEnvironment('modal')
        terminalLogic.actions.setSandboxSize('high_memory')
        terminalLogic.actions.start()
        await waitFor(() => expect(terminalLogic.values.status).toBe('ready'))
        const runtime = jest.mocked(ModalTerminalRuntime).mock.results[0].value
        expect(runtime.start).toHaveBeenCalledWith('high_memory')
        expect(TerminalRuntime).not.toHaveBeenCalled()
        window.posthogTerminal?.write('pwd\r')
        expect(runtime.write).toHaveBeenCalledWith('pwd\r')
        let finishStop!: () => void
        runtime.stop.mockReturnValue(
            new Promise<void>((resolve) => {
                finishStop = resolve
            })
        )
        terminalLogic.actions.stop()
        expect(terminalLogic.values.status).toBe('stopping')
        terminalLogic.actions.start()
        expect(ModalTerminalRuntime).toHaveBeenCalledTimes(1)
        finishStop()
        await waitFor(() => expect(terminalLogic.values.status).toBe('idle'))
        expect(window.posthogTerminal).toBeUndefined()
    })

    it.each([false, true])('waits for Modal cleanup on project changes, with explicit Stop: %s', async (stop) => {
        terminalLogic.actions.setEnvironment('modal')
        terminalLogic.actions.attach(document.createElement('div'))
        terminalLogic.actions.start()
        await waitFor(() => expect(terminalLogic.values.status).toBe('ready'))
        const runtime = jest.mocked(ModalTerminalRuntime).mock.results[0].value
        let finishStop!: () => void
        runtime.stop.mockReturnValue(new Promise<void>((resolve) => (finishStop = resolve)))
        const nextProjectId = MOCK_DEFAULT_TEAM.id + 1
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: nextProjectId })
        expect(terminalLogic.values.status).toBe('stopping')
        expect(ModalTerminalRuntime).toHaveBeenCalledTimes(1)
        if (stop) {
            terminalLogic.actions.stop()
        }
        finishStop()
        await waitFor(() => expect(terminalLogic.values.status).toBe(stop ? 'idle' : 'ready'))
        expect(ModalTerminalRuntime).toHaveBeenCalledTimes(stop ? 1 : 2)
        if (!stop) {
            expect(ModalTerminalRuntime).toHaveBeenLastCalledWith(
                String(nextProjectId),
                expect.any(Function),
                expect.any(Function)
            )
        }
    })

    it.each([false, true])('opens folders with the simple side panel enabled: %s', (enabled) => {
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.POSTHOG_TERMINAL]: true,
            [FEATURE_FLAGS.SIMPLE_SIDEPANEL]: enabled,
        })
        const push = jest.spyOn(router.actions, 'push')
        const url = urls.projectFiles('Research & notes/Reports')
        terminalLogic.actions.openUrl(url)
        if (enabled) {
            expect(push).not.toHaveBeenCalled()
            expect(panelLayoutLogic.values.navExperimentActiveTab).toBe('files')
            expect(projectTreeLogic({ key: FILES_TREE_KEY, root: 'project://' }).values.expandedFolders).toContain(
                'project://Research & notes/Reports'
            )
        } else {
            expect(push).toHaveBeenCalledWith(url)
        }
        terminalLogic.actions.openUrl('/insights/example')
        expect(push).toHaveBeenCalledWith('/insights/example')
    })

    it.each([true, false])('keeps project-qualified folder links in their own project: %s', (sameProject) => {
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.POSTHOG_TERMINAL]: true,
            [FEATURE_FLAGS.SIMPLE_SIDEPANEL]: true,
        })
        const push = jest.spyOn(router.actions, 'push')
        const projectId = MOCK_DEFAULT_TEAM.id + (sameProject ? 0 : 1)
        const url = `/project/${projectId}/files?folder=Reports`
        terminalLogic.actions.openUrl(url)
        if (sameProject) {
            expect(push).not.toHaveBeenCalled()
        } else {
            expect(push).toHaveBeenCalledWith(url)
        }
    })

    it('does not boot without the flag and stops an active session on revocation', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.POSTHOG_TERMINAL]: false })
        terminalLogic.actions.attach(document.createElement('div'))
        expect(TerminalRuntime).not.toHaveBeenCalled()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.POSTHOG_TERMINAL]: true })
        terminalLogic.actions.start()
        await waitFor(() => expect(terminalLogic.values.status).toBe('ready'))
        expect(jest.mocked(PosthogFilesystem).mock.results[0].value.load).not.toHaveBeenCalled()
        const runtime = jest.mocked(TerminalRuntime).mock.results[0].value
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.POSTHOG_TERMINAL]: false })
        expect(runtime.dispose).toHaveBeenCalledTimes(1)
        expect(window.posthogTerminal).toBeUndefined()
        expect(terminalLogic.values.status).toBe('idle')
    })

    it('interrupts the foreground program when closing the display but keeps the terminal running', async () => {
        terminalLogic.actions.attach(document.createElement('div'))
        terminalLogic.actions.start()
        await waitFor(() => expect(terminalLogic.values.status).toBe('ready'))
        const runtime = jest.mocked(TerminalRuntime).mock.results[0].value
        terminalLogic.actions.setDisplayOpen(true)
        terminalDockLogic.actions.setDockOpen(false)
        terminalLogic.actions.setDisplayError('Display error')
        terminalLogic.actions.closeDisplay()
        expect(terminalDockLogic.values.dockOpen).toBe(true)
        expect(terminalLogic.values.displayError).toBeNull()
        expect(terminalLogic.values.displayOpen).toBe(false)
        expect(runtime.write).toHaveBeenCalledWith('\x03')
        expect(runtime.displayInput.release).toHaveBeenCalled()
        expect(runtime.dispose).not.toHaveBeenCalled()
        expect(terminalLogic.values.status).toBe('ready')
        terminalLogic.actions.setDisplayOpen(true)
        terminalLogic.actions.stop()
        expect(terminalLogic.values.displayOpen).toBe(false)
    })

    it('preserves Stop across reattachment and project changes', async () => {
        terminalLogic.actions.attach(document.createElement('div'))
        terminalLogic.actions.start()
        await waitFor(() => expect(terminalLogic.values.status).toBe('ready'))
        terminalLogic.actions.stop()
        terminalLogic.actions.attach(document.createElement('div'))
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: MOCK_DEFAULT_TEAM.id + 1 })
        expect(TerminalRuntime).toHaveBeenCalledTimes(1)
        expect(terminalLogic.values.runRequested).toBe(false)
    })

    it('opens the selected folder on first boot and changes it in an existing terminal', async () => {
        terminalDockLogic.actions.openInTerminal('Research')
        terminalLogic.actions.attach(document.createElement('div'))
        terminalLogic.actions.start()
        await waitFor(() => expect(terminalLogic.values.status).toBe('ready'))
        const runtime = jest.mocked(TerminalRuntime).mock.results[0].value
        expect(runtime.start).toHaveBeenCalledWith(
            expect.anything(),
            expect.anything(),
            expect.any(Function),
            '/posthog/files/Research'
        )
        terminalDockLogic.actions.openInTerminal('Research/Reports')
        await waitFor(() => expect(runtime.changeDirectory).toHaveBeenCalledWith('/posthog/files/Research/Reports'))
        expect(TerminalRuntime).toHaveBeenCalledTimes(1)
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.POSTHOG_TERMINAL]: false })
        terminalDockLogic.actions.openInTerminal('Hidden')
        expect(terminalDockLogic.values.dockOpen).toBe(false)
        expect(terminalDockLogic.values.requestedFolder).toBe(null)
    })

    it('retries a requested start when the project arrives', async () => {
        teamLogic.actions.loadCurrentTeamSuccess(null)
        terminalLogic.actions.attach(document.createElement('div'))
        terminalLogic.actions.start()
        expect(TerminalRuntime).not.toHaveBeenCalled()
        teamLogic.actions.loadCurrentTeamSuccess(MOCK_DEFAULT_TEAM)
        await waitFor(() => expect(terminalLogic.values.status).toBe('ready'))
        expect(TerminalRuntime).toHaveBeenCalledTimes(1)
    })

    it.each([
        ['lookup', 'request'],
        ['lookup', 'navigation'],
        ['boot', 'request'],
        ['boot', 'navigation'],
    ])('keeps a newer folder from %s during %s', async (phase, source) => {
        let resolveFolder!: (folder: string) => void
        mockFolderFor.mockImplementationOnce(
            () =>
                new Promise((resolve) => {
                    resolveFolder = resolve
                })
        )
        const projectTreeRef = jest.spyOn(breadcrumbsLogic.selectors, 'projectTreeRef')
        projectTreeRef.mockReturnValue({ type: 'folder', ref: 'Original' })
        terminalDockLogic.actions.setDockOpen(true)
        terminalLogic.actions.attach(document.createElement('div'))
        terminalLogic.actions.start()
        const runtime = jest.mocked(TerminalRuntime).mock.results[0].value
        let ready!: () => void
        runtime.start.mockImplementationOnce(async (_server: unknown, _signal: AbortSignal, onReady: () => void) => {
            ready = onReady
            if (phase === 'lookup') {
                ready()
            }
        })
        if (phase === 'boot') {
            resolveFolder('/posthog/files/Original')
            await waitFor(() => expect(runtime.start).toHaveBeenCalled())
        }
        if (source === 'request') {
            terminalDockLogic.actions.openInTerminal('Latest')
        } else {
            projectTreeRef.mockReturnValue({ type: 'folder', ref: 'Latest' })
            mockFolderFor.mockResolvedValue('/posthog/files/Latest')
        }
        if (phase === 'lookup') {
            resolveFolder('/posthog/files/Original')
        } else {
            ready()
        }
        await waitFor(() => expect(runtime.changeDirectory).toHaveBeenCalledWith('/posthog/files/Latest'))
        expect(terminalDockLogic.values.requestedFolder).toBeNull()
    })

    it('restores the command menu opener after the dialog element disappears', () => {
        commandLogic.mount()
        const opener = document.createElement('button')
        const dialog = document.createElement('div')
        dialog.setAttribute('role', 'dialog')
        const result = document.createElement('button')
        dialog.appendChild(result)
        document.body.append(opener, dialog)
        opener.focus()
        commandLogic.actions.openCommand('keyboard-shortcut')
        result.focus()
        terminalDockLogic.actions.setDockOpen(true)
        dialog.remove()
        terminalDockLogic.actions.setDockOpen(false)
        expect(document.activeElement).toBe(opener)
        opener.remove()
    })

    it.each(['cancel', 'stop', 'project', 'unmount', 'approve'] as const)(
        'blocks input until a click and settles pending approval on %s',
        async (finish) => {
            terminalLogic.actions.attach(document.createElement('div'))
            terminalLogic.actions.start()
            await waitFor(() => expect(terminalLogic.values.status).toBe('ready'))
            const confirm = jest.mocked(PosthogFilesystem).mock.calls[0][2]!
            const request: TerminalConfirmation = {
                title: 'Delete?',
                description: 'Delete a notebook',
                items: ['note1'],
            }
            const pending = confirm(request)
            await waitFor(() => expect(terminalLogic.values.confirmation).toBe(request))
            for (const key of ['Enter', ' ', 'Escape', '`']) {
                const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true })
                document.dispatchEvent(event)
                expect(event.defaultPrevented).toBe(true)
            }
            window.posthogTerminal!.write('rm -rf Research\n')
            expect(jest.mocked(TerminalRuntime).mock.results[0].value.write).not.toHaveBeenCalled()
            expect(terminalLogic.values.confirmation).toBe(request)
            if (finish === 'stop') {
                terminalLogic.actions.stop()
            } else if (finish === 'project') {
                teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: MOCK_DEFAULT_TEAM.id + 1 })
            } else if (finish === 'unmount') {
                terminalLogic.unmount()
            } else {
                terminalLogic.actions.answerConfirmation(request, finish === 'approve')
            }
            await expect(pending).resolves.toBe(finish === 'approve')
            const event = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })
            document.dispatchEvent(event)
            expect(event.defaultPrevented).toBe(false)
        }
    )
})
