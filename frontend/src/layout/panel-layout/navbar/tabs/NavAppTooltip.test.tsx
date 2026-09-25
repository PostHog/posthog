import { render, screen } from '@testing-library/react'

import { NavAppTooltip } from './NavAppTooltip'

describe('NavAppTooltip', () => {
    it('keeps group metadata when the group shares a built-in app name', () => {
        render(<NavAppTooltip item={{ path: 'Persons', type: 'group_0', href: '/groups/0' }} />)

        expect(screen.getByText(/Understand usage at the group level/)).toBeTruthy()
        expect(screen.getByText('Compare activity across customer accounts.')).toBeTruthy()
        expect(screen.queryByText(/Explore the people behind your events/)).toBeNull()
    })
})
