import { fireEvent, render } from '@testing-library/react'

import { HogFunctionIcon } from './HogFunctionIcon'

jest.mock('react-intersection-observer', () => ({ useInView: () => ({ ref: jest.fn(), inView: true }) }))

describe('HogFunctionIcon', () => {
    it('shows the fallback hedgehog instead of a loading skeleton when the image fails to load', () => {
        const { container, getByText } = render(<HogFunctionIcon src="/static/services/missing.png" />)

        fireEvent.error(container.querySelector('img')!)

        expect(container.querySelector('img')).toBeNull()
        expect(container.querySelector('.LemonSkeleton')).toBeNull()
        getByText('🦔')
    })
})
