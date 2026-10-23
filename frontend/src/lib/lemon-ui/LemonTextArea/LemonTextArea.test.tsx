import { fireEvent, render } from '@testing-library/react'

import { LemonTextArea } from './LemonTextArea'

describe('LemonTextArea', () => {
    describe('Enter while composing with an IME', () => {
        it.each([
            ['isComposing is set (Chrome, Firefox)', { isComposing: true }],
            ['only keyCode 229 is reported (Safari)', { keyCode: 229 }],
        ])('hides the confirming Enter from onKeyDown and onPressEnter when %s', (_, eventInit) => {
            const onKeyDown = jest.fn()
            const onPressEnter = jest.fn()
            const { container } = render(<LemonTextArea value="" onKeyDown={onKeyDown} onPressEnter={onPressEnter} />)

            fireEvent.keyDown(container.querySelector('textarea')!, { key: 'Enter', ...eventInit })

            expect(onKeyDown).not.toHaveBeenCalled()
            expect(onPressEnter).not.toHaveBeenCalled()
        })

        it('passes a regular Enter to both onKeyDown and onPressEnter', () => {
            const onKeyDown = jest.fn()
            const onPressEnter = jest.fn()
            const { container } = render(
                <LemonTextArea value="draft" onKeyDown={onKeyDown} onPressEnter={onPressEnter} />
            )

            fireEvent.keyDown(container.querySelector('textarea')!, { key: 'Enter' })

            expect(onKeyDown).toHaveBeenCalledTimes(1)
            expect(onPressEnter).toHaveBeenCalledWith('draft')
        })

        it('still passes other keys to onKeyDown while composing', () => {
            const onKeyDown = jest.fn()
            const { container } = render(<LemonTextArea value="" onKeyDown={onKeyDown} />)

            fireEvent.keyDown(container.querySelector('textarea')!, { key: 'Escape', isComposing: true })

            expect(onKeyDown).toHaveBeenCalledTimes(1)
        })
    })

    describe('Enter while composing with an IME inside an Enter-handling parent', () => {
        // A dialog form that submits on Enter is the real-world parent. The consumer handler either
        // stops the Enter itself (as the workflow reject-reason field does) or has no handler at all.
        const stopsEnter = (e: React.KeyboardEvent): void => {
            if (e.key === 'Enter') {
                e.stopPropagation()
            }
        }

        it.each([
            ['isComposing is set', { isComposing: true }],
            ['only keyCode 229 is reported', { keyCode: 229 }],
        ])('does not let the confirming Enter reach the parent when %s', (_, eventInit) => {
            const onParentKeyDown = jest.fn()
            const { container } = render(
                <div onKeyDown={onParentKeyDown}>
                    <LemonTextArea value="" />
                    <LemonTextArea value="" onKeyDown={stopsEnter} />
                </div>
            )

            for (const field of Array.from(container.querySelectorAll('textarea'))) {
                fireEvent.keyDown(field, { key: 'Enter', ...eventInit })
            }

            expect(onParentKeyDown).not.toHaveBeenCalled()
        })

        it('does not preventDefault the confirming Enter', () => {
            const { container } = render(<LemonTextArea value="" />)
            const notPrevented = fireEvent.keyDown(container.querySelector('textarea')!, {
                key: 'Enter',
                isComposing: true,
            })

            expect(notPrevented).toBe(true)
        })

        it('keeps bubbling a regular Enter unless the consumer stops it', () => {
            const onParentKeyDown = jest.fn()
            const { container } = render(
                <div onKeyDown={onParentKeyDown}>
                    <LemonTextArea value="" />
                    <LemonTextArea value="" onKeyDown={stopsEnter} />
                </div>
            )
            const [plain, stopping] = Array.from(container.querySelectorAll('textarea'))

            fireEvent.keyDown(stopping, { key: 'Enter' })
            expect(onParentKeyDown).not.toHaveBeenCalled()

            fireEvent.keyDown(plain, { key: 'Enter' })
            expect(onParentKeyDown).toHaveBeenCalledTimes(1)
        })

        it('keeps bubbling other keys while composing', () => {
            const onParentKeyDown = jest.fn()
            const { container } = render(
                <div onKeyDown={onParentKeyDown}>
                    <LemonTextArea value="" />
                </div>
            )

            fireEvent.keyDown(container.querySelector('textarea')!, { key: 'Escape', isComposing: true })

            expect(onParentKeyDown).toHaveBeenCalledTimes(1)
        })
    })
})
