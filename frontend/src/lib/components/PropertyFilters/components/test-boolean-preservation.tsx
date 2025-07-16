import { useState } from 'react'
import { PropertyValue } from './PropertyValue'
import { PropertyFilterType, PropertyOperator } from '~/types'

/**
 * Test component to verify boolean preservation in PropertyValue
 * This demonstrates that boolean values are preserved when isFlagDependencyProperty is true
 */
export function TestBooleanPreservation(): JSX.Element {
    const [value, setValue] = useState<Array<boolean | string>>([true, false, 'some-variant'])

    return (
        <div>
            <h3>Boolean Preservation Test</h3>
            <p>Current value: {JSON.stringify(value)}</p>
            <p>Types: {value.map((v: boolean | string) => typeof v).join(', ')}</p>

            <PropertyValue
                propertyKey="testProp"
                type={PropertyFilterType.FlagDependency}
                operator={PropertyOperator.Exact}
                value={value}
                onSet={(newValue: boolean | string | Array<boolean | string>) => {
                    setValue(Array.isArray(newValue) ? newValue : [newValue])
                }}
                endpoint="test"
                eventNames={[]}
                addRelativeDateTimeOptions={false}
                groupTypeIndex={undefined}
                editable={true}
                preloadValues={false}
            />
        </div>
    )
}

// Mock the propertyDefinitionsModel

// This would be used in a story or test environment
export default TestBooleanPreservation
