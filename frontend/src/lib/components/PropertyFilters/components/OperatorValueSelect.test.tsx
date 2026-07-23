import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { PropertyDefinition, PropertyFilterType, PropertyOperator, PropertyType } from '~/types'

import { OperatorValueSelect } from './OperatorValueSelect'

jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    // Render a native select so operator options are directly assertable without popover mechanics
    LemonSelect: ({ onChange, options, value }: any): JSX.Element => {
        const flatOptions = options.flatMap((option: any) => ('options' in option ? option.options : option))
        return (
            <select
                data-attr="operator-select"
                value={value === undefined ? '' : String(value)}
                onChange={(event) => {
                    const selectedOption = flatOptions.find(
                        (option: any) => String(option.value) === event.target.value
                    )
                    onChange?.(selectedOption?.value)
                }}
            >
                {flatOptions.map((option: any) => (
                    <option key={String(option.value)} value={String(option.value)}>
                        {String(option.value)}
                    </option>
                ))}
            </select>
        )
    },
}))

const STARTS_ENDS_WITH_VALUES = ['starts_with', 'not_starts_with', 'ends_with', 'not_ends_with']

const emailPropertyDefinition = {
    id: '1',
    name: 'email',
    property_type: PropertyType.String,
} as PropertyDefinition

describe('OperatorValueSelect', () => {
    let unmountFeatureFlagLogic: (() => void) | null = null

    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/person/values': [],
                '/api/event/values': [],
            },
        })
        unmountFeatureFlagLogic = featureFlagLogic.mount()
    })

    afterEach(() => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        unmountFeatureFlagLogic?.()
        unmountFeatureFlagLogic = null
        cleanup()
    })

    function setStartsEndsWithFlag(enabled: boolean): void {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.STARTS_WITH_ENDS_WITH_OPERATORS], {
            [FEATURE_FLAGS.STARTS_WITH_ENDS_WITH_OPERATORS]: enabled,
        })
    }

    function renderSelect(operator?: PropertyOperator): void {
        render(
            <Provider>
                <OperatorValueSelect
                    type={PropertyFilterType.Person}
                    propertyKey="email"
                    operator={operator}
                    value={null}
                    editable
                    onChange={jest.fn()}
                    propertyDefinitions={[emailPropertyDefinition]}
                />
            </Provider>
        )
    }

    function renderedOperatorValues(): string[] {
        const select = screen.getByTestId('operator-select')
        return Array.from(select.querySelectorAll('option')).map((option) => option.value)
    }

    it('hides the starts_with/ends_with operator family when the flag is off', () => {
        setStartsEndsWithFlag(false)
        renderSelect()
        const values = renderedOperatorValues()
        for (const operatorValue of STARTS_ENDS_WITH_VALUES) {
            expect(values).not.toContain(operatorValue)
        }
        expect(values).toContain('icontains')
    })

    it('keeps a saved starts_with operator selectable when the flag is off, without resetting it', () => {
        setStartsEndsWithFlag(false)
        renderSelect(PropertyOperator.StartsWith)
        const values = renderedOperatorValues()
        expect(values).toContain('starts_with')
        expect(values).not.toContain('ends_with')
        expect(screen.getByTestId('operator-select')).toHaveValue('starts_with')
    })

    it('offers the full starts_with/ends_with operator family when the flag is on', () => {
        setStartsEndsWithFlag(true)
        renderSelect()
        const values = renderedOperatorValues()
        for (const operatorValue of STARTS_ENDS_WITH_VALUES) {
            expect(values).toContain(operatorValue)
        }
    })
})
