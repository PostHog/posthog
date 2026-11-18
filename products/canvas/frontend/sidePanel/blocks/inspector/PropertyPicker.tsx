import { useActions, useValues } from 'kea'

import { propertyDisplayName } from '../../../editing/blockLibrary/propertyNames'
import { canvasBlockPickersLogic } from './canvasBlockPickersLogic'
import { SearchPicker } from './SearchPicker'

/** Picks one event property, from the project's most common ones or typed in. */
export function PropertyPicker({
    value,
    onChange,
    allowNone,
    noneLabel,
}: {
    value: string | null
    onChange: (value: string | null) => void
    allowNone?: boolean
    noneLabel?: string
}): JSX.Element {
    const { topProperties, topPropertiesLoading, topPropertiesError } = useValues(canvasBlockPickersLogic)
    const { ensureTopProperties } = useActions(canvasBlockPickersLogic)
    return (
        <SearchPicker
            value={value}
            onChange={onChange}
            options={topProperties ?? []}
            loading={topPropertiesLoading}
            error={topPropertiesError ? 'Options did not load. Close and reopen this list to try again.' : null}
            onOpen={ensureTopProperties}
            placeholder="Pick a property"
            searchPlaceholder="Search properties…"
            ariaLabel="Property"
            format={propertyDisplayName}
            allowNone={allowNone}
            noneLabel={noneLabel}
        />
    )
}
