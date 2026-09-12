import { act, cleanup, fireEvent, render } from '@testing-library/react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { initKeaTests } from '~/test/init'

import { panelLayoutLogic } from '../panelLayoutLogic'
import { NavBar } from './NavBar'

jest.mock('lib/hooks/useFeatureFlag', () => ({ useFeatureFlag: jest.fn() }))
jest.mock('lib/components/Account/NewAccountMenu', () => ({ NewAccountMenu: () => <div /> }))
jest.mock('lib/components/NavSearchButton/NavSearchButton', () => ({
    NavSearchBar: () => <div />,
    NavSearchButton: () => <div />,
}))
jest.mock('lib/components/Resizer/Resizer', () => ({ Resizer: () => <div /> }))
jest.mock('./NavBarFooter', () => ({ NavBarFooter: () => <div /> }))
jest.mock('./PanelLayoutPanels', () => ({ PanelLayoutPanels: () => <div /> }))

const scrollTo = jest.fn()

function mockBrowse(scrollRef?: React.MutableRefObject<HTMLDivElement | null>): JSX.Element {
    return (
        <div
            ref={(el) => {
                // jsdom has no Element.scrollTo, so stand one in to observe the call.
                if (el && scrollRef) {
                    Object.assign(el, { scrollTo })
                    scrollRef.current = el
                }
            }}
        />
    )
}

jest.mock('./tabs/NavTabBrowse', () => ({ NavTabBrowse: ({ scrollRef }: any) => mockBrowse(scrollRef) }))
jest.mock('./tabs/flat-nav/FlatNavBrowse', () => ({ FlatNavBrowse: ({ scrollRef }: any) => mockBrowse(scrollRef) }))

describe('NavBar', () => {
    beforeEach(() => {
        initKeaTests()
        panelLayoutLogic.mount()
        scrollTo.mockClear()
    })

    afterEach(() => {
        cleanup()
    })

    // Both branches thread the same scroll ref, so the reselect behavior must hold for each.
    it.each([
        ['tree nav', false],
        ['flat nav', true],
    ])('acknowledges a click on the already-selected Browse tab (%s)', (_name, isFlatNav) => {
        ;(useFeatureFlag as jest.Mock).mockReturnValue(isFlatNav)
        const { getByTestId } = render(<NavBar />)

        act(() => panelLayoutLogic.actions.setActivePanelIdentifier('Project'))
        fireEvent.click(getByTestId('nav-tab-home'))

        expect(scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'smooth' })
        expect(panelLayoutLogic.values.activePanelIdentifier).toBe('')
        expect(panelLayoutLogic.values.isLayoutPanelVisible).toBe(false)
    })

    it('leaves an open panel alone when the click actually switches tabs', () => {
        ;(useFeatureFlag as jest.Mock).mockReturnValue(false)
        const { getByTestId } = render(<NavBar />)

        act(() => panelLayoutLogic.actions.setNavExperimentTab('chat'))
        act(() => panelLayoutLogic.actions.setActivePanelIdentifier('Project'))
        fireEvent.click(getByTestId('nav-tab-home'))

        expect(scrollTo).not.toHaveBeenCalled()
        expect(panelLayoutLogic.values.activePanelIdentifier).toBe('Project')
    })
})
