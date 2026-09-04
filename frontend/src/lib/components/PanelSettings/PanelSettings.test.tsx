import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'

import { SettingsMenu } from './PanelSettings'

describe('SettingsMenu', () => {
    it('forwards data-attr to the trigger button so the control is visible to analytics', () => {
        render(
            <SettingsMenu
                data-attr="bulk-action-menu"
                label="Actions"
                items={[{ label: 'Delete', onClick: () => {} }]}
            />
        )

        expect(screen.getByRole('button')).toHaveAttribute('data-attr', 'bulk-action-menu')
    })
})
