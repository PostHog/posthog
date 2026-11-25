import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'

import { initKeaTests } from '~/test/init'

import { uiSoundsLogic } from './uiSoundsLogic'

const mockPlayedSounds: string[] = []
const mockLoadedSounds: string[] = []
const mockReleasedSounds: string[] = []

jest.mock('button-sounds', () => ({
    setPath: () => {},
    load: (name: string) => mockLoadedSounds.push(name),
    press: (name: string) => mockPlayedSounds.push(name),
    release: (name: string) => mockReleasedSounds.push(name),
}))

describe('uiSoundsLogic', () => {
    let logic: ReturnType<typeof uiSoundsLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        logic = uiSoundsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        cleanup()
        mockPlayedSounds.length = 0
        mockLoadedSounds.length = 0
        mockReleasedSounds.length = 0
    })

    it('plays sounds only while the setting is on', async () => {
        const { container } = render(
            <>
                <LemonSwitch checked={false} onChange={() => {}} />
                <LemonButton>Save</LemonButton>
            </>
        )
        // jsdom has no PointerEvent, and a MouseEvent carries the `button` field that PointerEvent inherits from it.
        const pressDown = (selector: string): boolean =>
            fireEvent(container.querySelector(selector)!, new MouseEvent('pointerdown', { bubbles: true, button: 0 }))
        const pressSwitch = (): boolean => pressDown('[role="switch"]')
        const pressButton = (): boolean => pressDown('.LemonButton')

        pressSwitch()
        logic.actions.setUiSoundsEnabled(true)
        pressButton()

        // Every press waits on the same lazy import, so a sound from the first press would land before this one.
        await waitFor(() => expect(mockPlayedSounds).toEqual(['hi75-soft']))

        logic.actions.setUiSoundsEnabled(false)
        pressSwitch()
        logic.actions.setUiSoundsEnabled(true)
        pressSwitch()

        await waitFor(() => expect(mockPlayedSounds).toEqual(['hi75-soft', 'lock-closed']))
    })

    it('loads only the samples of a control the pointer reaches, and only while the setting is on', async () => {
        const { container } = render(
            <>
                <LemonSwitch checked={false} onChange={() => {}} />
                <LemonButton>Save</LemonButton>
            </>
        )
        const hoverSwitch = (): boolean =>
            fireEvent(container.querySelector('[role="switch"]')!, new MouseEvent('pointerover', { bubbles: true }))
        const pressButton = (): boolean =>
            fireEvent(
                container.querySelector('.LemonButton')!,
                new MouseEvent('pointerdown', { bubbles: true, button: 0 })
            )

        hoverSwitch()
        logic.actions.setUiSoundsEnabled(true)
        hoverSwitch()
        pressButton()

        // The press resolves after the hover, so the first hover's samples would already be in the list.
        await waitFor(() => expect(mockPlayedSounds).toEqual(['hi75-soft']))
        expect(mockLoadedSounds).toEqual(['lock-closed', 'lock-open'])
    })

    it('drops the release of a cancelled press, so the next click releases once', async () => {
        const { container } = render(<LemonButton>Save</LemonButton>)
        const press = (): boolean =>
            fireEvent(
                container.querySelector('.LemonButton')!,
                new MouseEvent('pointerdown', { bubbles: true, button: 0 })
            )
        logic.actions.setUiSoundsEnabled(true)

        press()
        fireEvent(window, new Event('pointercancel'))
        press()
        fireEvent(window, new Event('pointerup'))

        await waitFor(() => expect(mockReleasedSounds).toEqual(['hi75-soft']))
        await waitFor(() => expect(mockPlayedSounds).toEqual(['hi75-soft', 'hi75-soft']))
        expect(mockReleasedSounds).toEqual(['hi75-soft'])
    })
})
