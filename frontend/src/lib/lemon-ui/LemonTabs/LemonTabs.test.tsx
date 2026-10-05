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
})
