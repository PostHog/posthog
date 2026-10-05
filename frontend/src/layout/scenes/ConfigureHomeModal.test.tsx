import { render, screen } from '@testing-library/react'
import { type ReactNode } from 'react'

import { ConfigureHomeModal } from './ConfigureHomeModal'

jest.mock('lib/lemon-ui/LemonModal', () => ({
    LemonModal: ({ children }: { children: ReactNode }) => <>{children}</>,
}))

jest.mock('./ConfigureHomeModalContent', () => ({
    ConfigureHomeModalContent: () => <div data-attr="configure-home-content" />,
}))

describe('ConfigureHomeModal', () => {
    it('mounts homepage configuration only when open', () => {
        const { rerender } = render(<ConfigureHomeModal isOpen={false} onClose={jest.fn()} />)
        expect(screen.queryByTestId('configure-home-content')).toBeNull()

        rerender(<ConfigureHomeModal isOpen onClose={jest.fn()} />)
        expect(screen.getByTestId('configure-home-content')).not.toBeNull()
    })
})
