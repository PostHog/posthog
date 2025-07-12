import { LemonInputSelect } from './LemonInputSelect'

// Example usage demonstrating the new boolean support
export function BooleanExample(): JSX.Element {
    return (
        <LemonInputSelect<boolean | string>
            mode="multiple"
            options={[
                { key: 'bool-true', label: 'True', value: true },
                { key: 'bool-false', label: 'False', value: false },
                { key: 'some-variant', label: 'Some Variant', value: 'some-variant' },
                { key: 'string-true', label: 'String "true"', value: 'true' },
            ]}
            value={[true, false, 'some-variant']}
            onChange={() => {
                // In a real implementation, you would handle the selected values here
                // values will be: [true, false, 'some-variant']
                // Each value preserves its original type
            }}
        />
    )
}

// Backwards compatibility example
export function BackwardsCompatExample(): JSX.Element {
    return (
        <LemonInputSelect
            mode="multiple"
            options={[
                { key: 'option1', label: 'Option 1' },
                { key: 'option2', label: 'Option 2' },
            ]}
            value={['option1']}
            onChange={() => {
                // In a real implementation, you would handle the selected values here
                // values will be: ['option1']
                // Works exactly as before
            }}
        />
    )
}
