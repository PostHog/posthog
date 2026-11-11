import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { LemonTab, LemonTabs } from './LemonTabs'

const tabs = (keepLineageMounted: boolean): LemonTab<string>[] => [
    {
        key: 'overview',
        label: 'Overview',
        content: <input aria-label="Overview value" defaultValue="overview" />,
    },
    {
        key: 'lineage',
        label: 'Lineage',
        content: <input aria-label="Lineage value" defaultValue="lineage" />,
        keepMounted: keepLineageMounted,
    },
]

describe('LemonTabs', () => {
    it('keeps retained content state between tab changes', async () => {
        const user = userEvent.setup()
        const { rerender } = render(<LemonTabs activeKey="overview" tabs={tabs(false)} />)

        const overviewInput = screen.getByLabelText('Overview value')
        expect(screen.queryByLabelText('Lineage value')).not.toBeInTheDocument()

        rerender(<LemonTabs activeKey="lineage" tabs={tabs(true)} />)

        const lineageInput = screen.getByLabelText('Lineage value')
        await user.clear(lineageInput)
        await user.type(lineageInput, 'retained')
        expect(overviewInput).not.toBeInTheDocument()

        rerender(<LemonTabs activeKey="overview" tabs={tabs(true)} />)

        expect(lineageInput).toBeInTheDocument()
        expect(lineageInput.closest('.LemonTabs__content')).toHaveAttribute('hidden')

        rerender(<LemonTabs activeKey="lineage" tabs={tabs(true)} />)

        expect(screen.getByLabelText('Lineage value')).toBe(lineageInput)
        expect(lineageInput).toHaveValue('retained')
    })

    it('moves the underline to the active tab when a tab is inserted before it', () => {
        // jsdom has no layout, so place each tab 100px after the previous one.
        const offsetLeft = jest
            .spyOn(HTMLElement.prototype, 'offsetLeft', 'get')
            .mockImplementation(function (this: HTMLElement) {
                return this.parentElement ? Array.from(this.parentElement.children).indexOf(this) * 100 : 0
            })
        const offsetWidth = jest.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(80)
        try {
            const workflowTab = { key: 'workflow', label: 'Workflow', content: null }
            const { container, rerender } = render(<LemonTabs activeKey="workflow" tabs={[workflowTab]} />)
            const tabsElement = container.querySelector<HTMLElement>('.LemonTabs')!
            expect(tabsElement.style.getPropertyValue('--lemon-tabs-slider-offset')).toBe('0px')

            rerender(
                <LemonTabs
                    activeKey="workflow"
                    tabs={[{ key: 'overview', label: 'Overview', content: null }, workflowTab]}
                />
            )

            expect(tabsElement.style.getPropertyValue('--lemon-tabs-slider-offset')).toBe('100px')
        } finally {
            offsetLeft.mockRestore()
            offsetWidth.mockRestore()
        }
    })
})
