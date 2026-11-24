import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'

import { initKeaTests } from '~/test/init'

import { uiSoundsLogic } from './uiSoundsLogic'

const mockPlayedSounds: string[] = []

jest.mock('button-sounds', () => ({
    setPath: () => {},
    load: () => {},
    press: (name: string) => mockPlayedSounds.push(name),
    release: () => {},
}))

describe('uiSoundsLogic', () => {
    let logic: ReturnType<typeof uiSoundsLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = uiSoundsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        cleanup()
        mockPlayedSounds.length = 0
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

        await waitFor(() => expect(mockPlayedSounds).toEqual(['hi75-soft', 'tonal-on']))
    })
})
