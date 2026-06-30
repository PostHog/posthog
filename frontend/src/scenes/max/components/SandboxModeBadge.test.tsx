import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useValues } from 'kea'

import { SandboxModeBadge } from './InputFormArea'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
}))

jest.mock('../maxThreadLogic', () => ({
    maxThreadLogic: { __mock: 'maxThreadLogic' },
}))

describe('SandboxModeBadge', () => {
    afterEach(() => {
        cleanup()
        jest.clearAllMocks()
    })

    it.each([
        ['sandbox', 'plan', 'Plan mode'],
        ['sandbox', 'default', 'Default mode'],
    ])('renders the %s runtime in %s mode as a badge', (runtime, mode, label) => {
        ;(useValues as jest.Mock).mockReturnValue({
            conversation: { agent_runtime: runtime },
            sandboxCurrentMode: mode,
        })

        render(<SandboxModeBadge />)

        expect(screen.getByText(label)).toBeInTheDocument()
    })

    it.each([
        ['no mode has been reported', 'sandbox', null],
        ['the conversation is not sandbox-runtime', 'langgraph', 'plan'],
    ])('renders nothing when %s', (_case, runtime, mode) => {
        ;(useValues as jest.Mock).mockReturnValue({
            conversation: { agent_runtime: runtime },
            sandboxCurrentMode: mode,
        })

        const { container } = render(<SandboxModeBadge />)
        expect(container).toBeEmptyDOMElement()
    })
})
