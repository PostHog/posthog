import '@testing-library/jest-dom'

import { cleanup, fireEvent, render } from '@testing-library/react'
import { useValues } from 'kea'
import type { PropsWithChildren } from 'react'

import type { CustomPropertyDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountPropertiesInputLogic } from './accountPropertiesInputLogic'
import CyclotronJobInputAccountProperties from './CyclotronJobInputAccountProperties'

jest.mock('kea', () => ({ ...jest.requireActual('kea'), useValues: jest.fn() }))
jest.mock('lib/monaco/CodeEditorInline', () => ({
    CodeEditorInline: (): JSX.Element => <div />,
}))
jest.mock('lib/ui/quill', () => ({
    Combobox: ({ children }: PropsWithChildren): JSX.Element => <>{children}</>,
    ComboboxContent: ({ children }: PropsWithChildren): JSX.Element => <div>{children}</div>,
    ComboboxEmpty: ({ children }: PropsWithChildren): JSX.Element => <div>{children}</div>,
    ComboboxInput: (): JSX.Element => <input />,
    ComboboxItem: ({ children }: PropsWithChildren): JSX.Element => <div>{children}</div>,
    ComboboxList: (): null => null,
}))

describe('CyclotronJobInputAccountProperties', () => {
    const propertyDefinition: CustomPropertyDefinitionApi = {
        id: 'property-id',
        name: 'Text property',
        display_type: 'text',
        is_canonical: false,
        has_workflow_reference: false,
        source: null,
        created_at: '2026-01-01T00:00:00Z',
        created_by: 1,
        updated_at: null,
        references: [],
    }

    beforeEach(() => {
        ;(useValues as jest.Mock).mockImplementation((logic) => {
            if (logic === accountPropertiesInputLogic) {
                return { definitions: [propertyDefinition], definitionsLoading: false }
            }
            throw new Error('Unexpected logic')
        })
    })

    afterEach(cleanup)

    it('sets a cleared property value to null without removing its definition key', () => {
        const onChange = jest.fn()
        const { container } = render(
            <CyclotronJobInputAccountProperties
                schema={{
                    type: 'customer_analytics_account_properties',
                    key: 'account_properties',
                    label: 'Account properties',
                }}
                value={{ 'property-id': 'properties.plan' }}
                onChange={onChange}
            />
        )

        const clearButton = container.querySelector('[data-attr="account-properties-clear-property"]')
        expect(clearButton).toBeInTheDocument()
        fireEvent.click(clearButton as HTMLElement)

        expect(onChange).toHaveBeenCalledWith({ 'property-id': null })
    })
})
