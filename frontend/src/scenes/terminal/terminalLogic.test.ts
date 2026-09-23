import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { waitFor } from '@testing-library/react'

import { commandLogic } from 'lib/components/Command/commandLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { PosthogFilesystem } from './posthogFilesystem'
import { TerminalConfirmation } from './terminalConfirmation'
import { terminalDockLogic } from './terminalDockLogic'
import { terminalLogic } from './terminalLogic'
import { TerminalRuntime } from './terminalRuntime'

jest.mock('./terminalRuntime', () => ({
    TerminalRuntime: jest.fn().mockImplementation(() => ({
        start: jest.fn(async (_server, _signal, ready) => ready()),
        dispose: jest.fn(),
        resize: jest.fn(),
        syncClock: jest.fn(),
        read: jest.fn(() => ''),
        write: jest.fn(),
    })),
}))
jest.mock('./TerminalSession', () => ({
    TerminalSession: jest.fn().mockImplementation(() => ({
        attach: jest.fn(),
        detach: jest.fn(),
        dispose: jest.fn(),
        view: { clear: jest.fn(), write: jest.fn(), cols: 80, rows: 24 },
    })),
}))
jest.mock('./posthogFilesystem', () => ({
    PosthogFilesystem: jest.fn().mockImplementation(() => ({ load: jest.fn(async () => {}) })),
}))
jest.mock('./posthogCommands', () => ({ PosthogCommands: jest.fn() }))

describe('terminal lifecycle', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.POSTHOG_TERMINAL]: true })
        terminalLogic.mount()
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

    it('preserves Stop across reattachment and project changes', async () => {
        terminalLogic.actions.attach(document.createElement('div'))
        await waitFor(() => expect(terminalLogic.values.status).toBe('ready'))
        terminalLogic.actions.stop()
        terminalLogic.actions.attach(document.createElement('div'))
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: MOCK_DEFAULT_TEAM.id + 1 })
        expect(TerminalRuntime).toHaveBeenCalledTimes(1)
        expect(terminalLogic.values.runRequested).toBe(false)
    })

    it('retries a requested start when the project arrives', async () => {
        teamLogic.actions.loadCurrentTeamSuccess(null)
        terminalLogic.actions.attach(document.createElement('div'))
        expect(TerminalRuntime).not.toHaveBeenCalled()
        teamLogic.actions.loadCurrentTeamSuccess(MOCK_DEFAULT_TEAM)
        await waitFor(() => expect(terminalLogic.values.status).toBe('ready'))
        expect(TerminalRuntime).toHaveBeenCalledTimes(1)
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
