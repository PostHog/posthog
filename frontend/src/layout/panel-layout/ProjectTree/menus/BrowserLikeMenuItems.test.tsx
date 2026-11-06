import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { DropdownMenu, DropdownMenuContent } from 'lib/ui/DropdownMenu/DropdownMenu'

import { BrowserLikeMenuItems } from './BrowserLikeMenuItems'

describe('BrowserLikeMenuItems', () => {
    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it.each([
        ['javascript:void(0)', false],
        ['  JaVaScRiPt:void(0)', false],
        ['java\tscr\nipt:void(0)', false],
        ['vbscript:MsgBox(1)', false],
        ['/project/1/insights', true],
        ['https://example.com/report', true],
    ])('checks the scheme before opening %s', (href, allowed) => {
        const open = jest.spyOn(window, 'open').mockImplementation(() => null)
        const onClick = jest.fn()
        render(
            <DropdownMenu defaultOpen>
                <DropdownMenuContent>
                    <BrowserLikeMenuItems href={href} onClick={onClick} />
                </DropdownMenuContent>
            </DropdownMenu>
        )

        fireEvent.click(screen.getByText('Open link in new browser tab'))

        if (allowed) {
            expect(open).toHaveBeenCalledWith(href, '_blank')
            expect(onClick).toHaveBeenCalledTimes(1)
        } else {
            expect(open).not.toHaveBeenCalled()
            expect(onClick).not.toHaveBeenCalled()
        }
    })
})
