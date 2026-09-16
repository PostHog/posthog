import { render, screen } from '@testing-library/react'

import { ByokModelPickerNotice } from './ByokModelPickerNotice'

describe('ByokModelPickerNotice', () => {
    it('tells a team with no provider keys how to get models', () => {
        render(<ByokModelPickerNotice hasGroups={false} loading={false} loadFailed={false} onRetry={jest.fn()} />)

        expect(screen.getByText(/No models available/)).toBeTruthy()
        expect(screen.getByText('Add your own API keys')).toBeTruthy()
    })

    it('stays silent while the keys and models are still loading', () => {
        const { container } = render(
            <ByokModelPickerNotice hasGroups={false} loading={true} loadFailed={false} onRetry={jest.fn()} />
        )

        expect(container.innerHTML).toBe('')
    })

    it('reports a failed model load and offers a retry', () => {
        render(<ByokModelPickerNotice hasGroups={false} loading={false} loadFailed={true} onRetry={jest.fn()} />)

        expect(screen.getByText(/Couldn't load models/)).toBeTruthy()
        expect(document.querySelector('[data-attr="byok-models-retry"]')).toBeTruthy()
    })
})
