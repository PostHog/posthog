import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'

jest.mock('kea', () => ({
    useValues: () => ({ isDarkModeOn: false }),
}))

jest.mock('~/layout/navigation-3000/themeLogic', () => ({
    themeLogic: { values: {} },
}))

const initializeMock = jest.fn()
const renderMock = jest.fn()

jest.mock('mermaid', () => ({
    __esModule: true,
    default: {
        initialize: (...args: unknown[]) => initializeMock(...args),
        render: (...args: unknown[]) => renderMock(...args),
    },
}))

import { MermaidDiagram } from './MermaidDiagram'

describe('MermaidDiagram', () => {
    afterEach(() => {
        cleanup()
        initializeMock.mockReset()
        renderMock.mockReset()
    })

    it('shows a loading spinner before mermaid resolves', () => {
        renderMock.mockReturnValue(new Promise(() => {}))
        render(<MermaidDiagram code="flowchart LR; A-->B" />)
        expect(screen.getByTestId('mermaid-loading')).toBeInTheDocument()
    })

    it('injects the rendered SVG when mermaid resolves', async () => {
        renderMock.mockResolvedValue({ svg: '<svg data-testid="rendered"><g/></svg>' })
        render(<MermaidDiagram code="flowchart LR; A-->B" />)
        const container = await screen.findByTestId('mermaid-rendered')
        expect(container.innerHTML).toContain('<svg')
        expect(container.innerHTML).toContain('rendered')
    })

    it('falls back to the source and an error message when mermaid throws', async () => {
        renderMock.mockRejectedValue(new Error('Parse error: bad syntax'))
        render(<MermaidDiagram code="not-a-real-diagram" />)
        const errorContainer = await screen.findByTestId('mermaid-error')
        expect(errorContainer).toHaveTextContent('Could not render Mermaid diagram: Parse error: bad syntax')
        expect(errorContainer).toHaveTextContent('not-a-real-diagram')
    })

    it('reuses initialize across re-renders with the same theme', async () => {
        renderMock.mockResolvedValue({ svg: '<svg/>' })
        const { rerender } = render(<MermaidDiagram code="flowchart LR; A-->B" />)
        await waitFor(() => {
            if (renderMock.mock.calls.length < 1) {
                throw new Error('mermaid.render not called yet')
            }
        })
        const initCallsAfterFirst = initializeMock.mock.calls.length
        rerender(<MermaidDiagram code="flowchart LR; A-->C" />)
        await waitFor(() => {
            if (renderMock.mock.calls.length < 2) {
                throw new Error('mermaid.render not called twice yet')
            }
        })
        expect(initializeMock.mock.calls.length).toBe(initCallsAfterFirst)
    })
})
