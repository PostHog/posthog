import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { initKeaTests } from '~/test/init'

import { AccountPropertyConfigurator, AccountPropertyConfiguratorProps } from './AccountPropertyConfigurator'
import type { AccountPropertyDefaultOption, AccountPropertyOption } from './accountPropertyTypes'
import { QuillAccountPropertyConfigurator } from './QuillAccountPropertyConfigurator'

describe('AccountPropertyConfigurator', () => {
    const options: AccountPropertyOption[] = [
        { key: 'custom:plan', label: 'Plan', kind: 'custom' },
        { key: 'relationship:owner', label: 'Owner', kind: 'relationship' },
    ]
    const resetOptions: AccountPropertyDefaultOption[] = [
        {
            key: 'project',
            label: 'Project default',
            pinnedPropertyKeys: ['relationship:owner'],
            followedDefault: { kind: 'project' },
        },
        {
            key: 'role:csm',
            label: 'Customer success',
            pinnedPropertyKeys: ['relationship:owner', 'custom:plan'],
            followedDefault: { kind: 'role', role_id: 'csm' },
        },
    ]

    beforeEach(() => initKeaTests())
    afterEach(cleanup)

    const renderConfigurator = (
        saving: boolean,
        extraProps: Partial<AccountPropertyConfiguratorProps> = {},
        Component: typeof AccountPropertyConfigurator = AccountPropertyConfigurator
    ): { onSave: jest.Mock; onChange: jest.Mock; onReset: jest.Mock } => {
        const onSave = jest.fn()
        const onChange = jest.fn()
        const onReset = jest.fn()
        render(
            <Component
                isOpen
                options={options}
                pinnedPropertyKeys={['custom:plan']}
                saving={saving}
                onChange={onChange}
                onSave={onSave}
                onCancel={jest.fn()}
                onReset={onReset}
                {...extraProps}
            />
        )
        return { onSave, onChange, onReset }
    }

    it('saves the pinned keys when idle', () => {
        const { onSave } = renderConfigurator(false)
        fireEvent.click(screen.getByText('Save'))
        expect(onSave).toHaveBeenCalledWith(['custom:plan'])
    })

    it('issues no writes while a save is in flight', () => {
        const { onSave, onChange, onReset } = renderConfigurator(true, { resetOptions })
        fireEvent.click(screen.getByText('Save'))
        fireEvent.click(screen.getByLabelText('Remove Plan'))
        fireEvent.click(screen.getByText('Reset to default'))
        expect(onSave).not.toHaveBeenCalled()
        expect(onChange).not.toHaveBeenCalled()
        expect(onReset).not.toHaveBeenCalled()
        expect(screen.getByLabelText('Reorder Plan')).toBeDisabled()
        expect(screen.queryByText('Project default')).not.toBeInTheDocument()
    })

    it.each([
        ['Lemon', AccountPropertyConfigurator],
        ['Quill', QuillAccountPropertyConfigurator],
    ])('passes the chosen default to onReset without saving (%s)', async (_, Component) => {
        const { onReset, onSave } = renderConfigurator(false, { resetOptions }, Component)

        await userEvent.click(screen.getByText('Reset to default'))
        await userEvent.click(await screen.findByText('Customer success'))
        expect(onReset).toHaveBeenCalledWith(resetOptions[1])
        expect(onSave).not.toHaveBeenCalled()

        await userEvent.click(screen.getByText('Reset to default'))
        await userEvent.click(await screen.findByText('Project default'))
        expect(onReset).toHaveBeenLastCalledWith(resetOptions[0])
        expect(onSave).not.toHaveBeenCalled()
    })

    it.each([
        ['Lemon', AccountPropertyConfigurator],
        ['Quill', QuillAccountPropertyConfigurator],
    ])('omits the reset control when no reset options are provided (%s)', (_, Component) => {
        renderConfigurator(false, {}, Component)
        expect(screen.queryByText('Reset to default')).not.toBeInTheDocument()
    })
})
