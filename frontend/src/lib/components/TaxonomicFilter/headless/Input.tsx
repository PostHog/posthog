import { InputHTMLAttributes, forwardRef } from 'react'

import { InputGroup, InputGroupInput } from '@posthog/quill'

import { useTaxonomicFilterContext } from './context'

export interface TaxonomicFilterInputProps extends Omit<
    InputHTMLAttributes<HTMLInputElement>,
    // `prefix` exists on `HTMLAttributes` typed as `string` (RDFa);
    // we redeclare it as `ReactNode` for the slot, so omit the parent
    // version to avoid the structural mismatch error from ts.
    'value' | 'onChange' | 'onKeyDown' | 'prefix'
> {
    /** Override the placeholder produced by useTaxonomicFilter. */
    placeholder?: string
    /** Class on the wrapping InputGroup. */
    className?: string
    /** Class on the inner input element. */
    inputClassName?: string
    /** Slot rendered before the input (e.g. a search icon). */
    prefix?: React.ReactNode
    /** Slot rendered after the input (e.g. a clear button or count). */
    suffix?: React.ReactNode
}

/**
 * TaxonomicFilter search input.
 *
 * Wraps Quill's `<InputGroup>` + `<InputGroupInput>` (which themselves wrap
 * Base UI's `<Input>` primitive). Spreads `inputProps` from the orchestrator
 * onto the input element so search + keyboard nav are wired automatically.
 */
export const TaxonomicFilterInput = forwardRef<HTMLInputElement, TaxonomicFilterInputProps>(
    function TaxonomicFilterInput(
        { placeholder, className, inputClassName, prefix, suffix, ...rest },
        ref
    ): JSX.Element {
        const { inputProps } = useTaxonomicFilterContext()
        return (
            <InputGroup className={className}>
                {prefix}
                <InputGroupInput
                    ref={ref}
                    type="search"
                    data-attr="taxonomic-filter-searchfield"
                    className={inputClassName}
                    {...rest}
                    {...inputProps}
                    placeholder={placeholder ?? inputProps.placeholder}
                />
                {suffix}
            </InputGroup>
        )
    }
)
