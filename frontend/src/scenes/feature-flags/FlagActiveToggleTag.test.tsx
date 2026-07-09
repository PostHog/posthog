import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { FlagActiveToggleTag } from './FlagActiveToggleTag'

describe('FlagActiveToggleTag', () => {
    afterEach(() => {
        cleanup()
    })

    it('resolves a click to the opposite state', () => {
        const onToggle = jest.fn()
        render(<FlagActiveToggleTag active={true} onToggle={onToggle} />)

        fireEvent.click(screen.getByRole('switch'))
        expect(onToggle).toHaveBeenCalledWith(false)
    })

    it('drops clicks while a toggle is in flight', () => {
        const onToggle = jest.fn()
        render(<FlagActiveToggleTag active={true} toggling onToggle={onToggle} />)

        fireEvent.click(screen.getByRole('switch'))
        expect(onToggle).not.toHaveBeenCalled()
    })
})
