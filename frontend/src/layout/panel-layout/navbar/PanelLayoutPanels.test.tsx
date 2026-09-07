import { act, render } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { panelLayoutLogic } from '../panelLayoutLogic'
import { PanelLayoutPanels } from './PanelLayoutPanels'

jest.mock('../ProjectTree/ProjectTree', () => ({
    PROJECT_TREE_KEY: 'project-tree',
    ProjectTree: ({ root }: { root: string }) => <div data-attr="mock-tree" data-root={root} />,
}))
jest.mock('lib/components/NotificationsMenu/NotificationsPanel', () => ({
    NotificationsPanel: () => <div data-attr="mock-notifications" />,
}))
jest.mock('./tabs/NavTabChat', () => ({
    NavTabChat: () => <div data-attr="mock-chat" />,
}))

describe('PanelLayoutPanels', () => {
    beforeEach(() => {
        initKeaTests()
        panelLayoutLogic.mount()
    })

    function renderedTrees(container: HTMLElement): { root: string | null; hidden: boolean }[] {
        return Array.from(container.querySelectorAll('[data-attr="mock-tree"]')).map((tree) => ({
            root: tree.getAttribute('data-root'),
            hidden: !!tree.closest('.hidden'),
        }))
    }

    it('keeps previously opened panels mounted but hidden when switching', () => {
        const { container } = render(<PanelLayoutPanels />)
        expect(renderedTrees(container)).toEqual([])

        act(() => panelLayoutLogic.actions.setActivePanelIdentifier('Project'))
        expect(renderedTrees(container)).toEqual([{ root: 'project://', hidden: false }])

        // Switching must not tear down the project tree — it stays in the DOM, hidden.
        act(() => panelLayoutLogic.actions.setActivePanelIdentifier('Products'))
        expect(renderedTrees(container)).toEqual([
            { root: 'project://', hidden: true },
            { root: 'products://', hidden: false },
        ])

        act(() => panelLayoutLogic.actions.clearActivePanelIdentifier())
        expect(renderedTrees(container)).toEqual([
            { root: 'project://', hidden: true },
            { root: 'products://', hidden: true },
        ])
    })

    it('mounts the notifications panel only while it is the active panel', () => {
        const { container } = render(<PanelLayoutPanels />)

        act(() => panelLayoutLogic.actions.setActivePanelIdentifier('Notifications'))
        expect(container.querySelector('[data-attr="mock-notifications"]')).toBeTruthy()

        // Notifications is excluded from keep-mounted: its logic drives unread/read semantics.
        act(() => panelLayoutLogic.actions.clearActivePanelIdentifier())
        expect(container.querySelector('[data-attr="mock-notifications"]')).toBeNull()
    })
})
