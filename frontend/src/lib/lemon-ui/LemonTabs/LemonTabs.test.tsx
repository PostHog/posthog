import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'

import { LemonTabs } from './LemonTabs'

function TestTabs(): JSX.Element {
    const [activeKey, setActiveKey] = useState('overview')

    return (
        <LemonTabs
            activeKey={activeKey}
            onChange={setActiveKey}
            tabs={[
                {
                    key: 'overview',
                    label: 'Overview',
                    content: <input aria-label="Overview value" defaultValue="overview" />,
                },
                {
                    key: 'lineage',
                    label: 'Lineage',
                    content: <input aria-label="Lineage value" defaultValue="lineage" />,
                    keepMounted: true,
                },
            ]}
        />
    )
}

describe('LemonTabs', () => {
    it('mounts retained content on demand and keeps its state between tab changes', async () => {
        const user = userEvent.setup()
        render(<TestTabs />)

        const overviewInput = screen.getByLabelText('Overview value')
        expect(screen.queryByLabelText('Lineage value')).not.toBeInTheDocument()

        await user.click(screen.getByText('Lineage'))

        const lineageInput = screen.getByLabelText('Lineage value')
        await user.clear(lineageInput)
        await user.type(lineageInput, 'retained')
        expect(overviewInput).not.toBeInTheDocument()

        await user.click(screen.getByText('Overview'))

        expect(lineageInput).toBeInTheDocument()
        expect(lineageInput.closest('.LemonTabs__content')).toHaveAttribute('hidden')

        await user.click(screen.getByText('Lineage'))

        expect(screen.getByLabelText('Lineage value')).toBe(lineageInput)
        expect(lineageInput).toHaveValue('retained')
    })
})
