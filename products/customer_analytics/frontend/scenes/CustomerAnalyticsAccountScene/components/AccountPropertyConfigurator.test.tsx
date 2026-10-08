import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { AccountPropertyConfigurator } from './AccountPropertyConfigurator'
import type { AccountPropertyOption } from './accountPropertyTypes'

describe('AccountPropertyConfigurator', () => {
    const options: AccountPropertyOption[] = [
        { key: 'custom:plan', label: 'Plan', kind: 'custom' },
        { key: 'relationship:owner', label: 'Owner', kind: 'relationship' },
    ]

    beforeEach(() => initKeaTests())
    afterEach(cleanup)

    const renderConfigurator = (saving: boolean): { onSave: jest.Mock; onChange: jest.Mock } => {
        const onSave = jest.fn()
        const onChange = jest.fn()
        render(
            <AccountPropertyConfigurator
                isOpen
                options={options}
                pinnedPropertyKeys={['custom:plan']}
                saving={saving}
                onChange={onChange}
                onSave={onSave}
                onCancel={jest.fn()}
            />
        )
        return { onSave, onChange }
    }

    it('saves the pinned keys when idle', () => {
        const { onSave } = renderConfigurator(false)
        fireEvent.click(screen.getByText('Save'))
        expect(onSave).toHaveBeenCalledWith(['custom:plan'])
    })

    it('issues no writes while a save is in flight', () => {
        const { onSave, onChange } = renderConfigurator(true)
        fireEvent.click(screen.getByText('Save'))
        fireEvent.click(screen.getByLabelText('Remove Plan'))
        expect(onSave).not.toHaveBeenCalled()
        expect(onChange).not.toHaveBeenCalled()
        expect(screen.getByLabelText('Reorder Plan')).toBeDisabled()
    })
})
