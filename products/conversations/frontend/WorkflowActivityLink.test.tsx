import { render } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { workflowsLogic } from 'products/workflows/frontend/Workflows/workflowsLogic'

import { WorkflowActivityLink } from './WorkflowActivityLink'

describe('WorkflowActivityLink', () => {
    let logic: ReturnType<typeof workflowsLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = workflowsLogic()
        logic.mount()
        // Populate via the loader success so the on-mount effect doesn't fire a real request.
        logic.actions.loadWorkflowsSuccess([
            { id: 'flow-1', name: 'Escalation workflow' },
            { id: 'flow-2', name: 'Billing workflow' },
        ] as any)
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('renders the current workflow name resolved by id, not from the log', () => {
        const { container } = render(<WorkflowActivityLink id="flow-1" />)
        expect(container.textContent).toContain('Escalation workflow')
        expect(container.querySelector('a')?.getAttribute('href')).toContain('flow-1')
    })

    it('falls back to a generic label when the workflow is not found', () => {
        const { container } = render(<WorkflowActivityLink id="missing" />)
        expect(container.textContent).toContain('A workflow')
    })
})
