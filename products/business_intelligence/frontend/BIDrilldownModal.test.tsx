import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { BIField, BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { biDrilldownLogic } from './biDrilldownLogic'
import { BIDrilldownModal } from './BIDrilldownModal'
import { buildBIQuery, DEFAULT_BI_CONFIG, getBIResultDimensions } from './biEditorTypes'

beforeEach(() => initKeaTests())
afterEach(cleanup)

it('disables hierarchy navigation while edits are pending without opening a new worksheet', () => {
    const field = (name: string): BIField => ({
        id: name,
        name,
        expression: name,
        type: 'string',
        source: { table: 'events' },
    })
    const country = field('country')
    const config = {
        ...DEFAULT_BI_CONFIG,
        source: country.source,
        rows: [country],
        hierarchies: [{ id: 'geo', name: 'Geography', levels: [country, field('city')] }],
    }
    const query: BIVisualizationNode = { ...buildBIQuery(config)!.node, kind: NodeKind.BIVisualizationNode, config }
    const props = { key: 'pending-hierarchy', query }
    const logic = biDrilldownLogic(props)
    const unmount = logic.mount()
    logic.actions.inspect({ [getBIResultDimensions(config)[0].column]: 'Example country', count: 4 })
    const navigate = jest.fn()
    const { rerender } = render(
        <BIDrilldownModal
            logicProps={props}
            onNavigate={navigate}
            navigationDisabledReason="Run the worksheet before drilling into edited fields"
        />
    )
    const drill = screen.getByText('Drill to city').closest('button')!
    expect(drill).toHaveAttribute('aria-disabled', 'true')
    expect(screen.getByText('Drill to city').closest('a')).toBeNull()
    fireEvent.click(drill)
    expect(navigate).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    rerender(<BIDrilldownModal logicProps={props} onNavigate={navigate} />)
    fireEvent.click(screen.getByText('Drill to city'))
    expect(navigate).toHaveBeenCalledTimes(1)
    expect(navigate.mock.calls[0][0].config.rows[0].name).toBe('city')
    unmount()
})
