import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { TooltipProvider } from '@posthog/quill'

import { initKeaTests } from '~/test/init'

import { TodaySceneTabsList } from './TodaySceneTabsList'

const tabs = [
    { key: 'a', label: 'Alpha', 'data-attr': 'tab-a' },
    { key: 'b', label: 'Beta', link: '/beta', 'data-attr': 'tab-b' },
    { key: 'c', label: 'Gamma', disabledReason: 'Not available', 'data-attr': 'tab-c' },
    { key: 'd', label: 'Delta', link: '/delta', disabledReason: 'Not available', 'data-attr': 'tab-d' },
]

describe('TodaySceneTabsList', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(cleanup)

    function setup(onChange: jest.Mock): void {
        render(
            <TooltipProvider>
                <TodaySceneTabsList tabs={tabs} activeKey="a" onChange={onChange} />
            </TooltipProvider>
        )
    }

    it('renders link tabs as anchors and marks the active row', () => {
        setup(jest.fn())
        expect(screen.getByText('Beta').closest('a')).toHaveAttribute('href', expect.stringContaining('/beta'))
        expect(document.querySelector('[data-attr="tab-a"]')).toHaveAttribute('aria-current', 'page')
        expect(document.querySelector('[data-attr="tab-b"]')).not.toHaveAttribute('aria-current')
    })

    it('calls onChange for enabled tabs only', async () => {
        const onChange = jest.fn()
        setup(onChange)
        await userEvent.click(document.querySelector('[data-attr="tab-a"]') as Element)
        expect(onChange).toHaveBeenCalledWith('a')
        onChange.mockClear()
        await userEvent.click(document.querySelector('[data-attr="tab-c"]') as Element)
        expect(onChange).not.toHaveBeenCalled()
    })

    it('does not link a disabled tab', () => {
        setup(jest.fn())
        expect(screen.getByText('Delta').closest('a')).toBeNull()
        expect(document.querySelector('[data-attr="tab-d"]')).toHaveAttribute('aria-disabled', 'true')
    })
})
