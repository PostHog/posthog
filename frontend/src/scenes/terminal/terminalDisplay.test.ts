import { TerminalDisplayInput } from './terminalDisplay'

describe('terminal display input', () => {
    it('releases held keys and mouse buttons on focus loss without repeating presses', () => {
        const keyboard = jest.fn()
        const mouse = jest.fn()
        const input = new TerminalDisplayInput(keyboard, mouse)
        input.key('ArrowUp', true)
        input.key('ControlLeft', true)
        input.key('ArrowUp', true)
        input.buttons(1)
        input.buttons(3)
        input.buttons(3)
        input.buttons(2)
        input.buttons(0)
        expect(keyboard).toHaveBeenCalledTimes(2)
        input.buttons(3)
        input.release()
        input.release()
        expect(keyboard.mock.calls).toEqual([[[0xe0, 0x48]], [[0x1d]], [[0xe0, 0xc8]], [[0x9d]]])
        expect(mouse.mock.calls).toEqual([
            [[true, false, false]],
            [[true, false, true]],
            [[false, false, true]],
            [[false, false, false]],
            [[true, false, true]],
            [[false, false, false]],
        ])
        expect(input.key('Unidentified', true)).toBe(false)
    })
})
