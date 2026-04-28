import '@testing-library/jest-dom'

import { render, waitFor } from '@testing-library/react'

import { SourceFieldSelectConfig } from '~/queries/schema/schema-general'

import { SelectFieldInput } from './SelectFieldInput'

const makeField = (overrides?: Partial<SourceFieldSelectConfig>): SourceFieldSelectConfig => ({
    type: 'select',
    name: 'using_ssl',
    label: 'Use SSL?',
    required: true,
    defaultValue: 'true',
    options: [
        { value: 'true', label: 'Yes' },
        { value: 'false', label: 'No' },
    ],
    ...overrides,
})

describe('SelectFieldInput', () => {
    it.each([
        [
            'seeds defaultValue when form state is undefined',
            { value: undefined, lastValue: undefined, defaultValue: 'true' },
            'true',
        ],
        [
            'seeds defaultValue when form state is null',
            { value: null, lastValue: undefined, defaultValue: 'true' },
            'true',
        ],
        [
            'prefers lastValue over defaultValue when form state is empty',
            { value: undefined, lastValue: { using_ssl: 'false' }, defaultValue: 'true' },
            'false',
        ],
    ])('%s', async (_label, { value, lastValue, defaultValue }, expected) => {
        const onChange = jest.fn()
        render(
            <SelectFieldInput
                field={makeField({ defaultValue })}
                value={value}
                lastValue={lastValue}
                onChange={onChange}
                renderOptionFields={() => <div />}
            />
        )

        await waitFor(() => expect(onChange).toHaveBeenCalledWith(expected))
        expect(onChange).toHaveBeenCalledTimes(1)
    })

    it('does not seed when form state already has a value', () => {
        const onChange = jest.fn()
        render(
            <SelectFieldInput
                field={makeField()}
                value="false"
                onChange={onChange}
                renderOptionFields={() => <div />}
            />
        )

        expect(onChange).not.toHaveBeenCalled()
    })

    it('does not seed when both lastValue and defaultValue are missing', () => {
        const onChange = jest.fn()
        render(
            <SelectFieldInput
                field={makeField({ defaultValue: '' })}
                value={undefined}
                onChange={onChange}
                renderOptionFields={() => <div />}
            />
        )

        expect(onChange).not.toHaveBeenCalled()
    })
})
