import { useId } from 'react'

import {
    Badge,
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    Credenza,
    CredenzaBody,
    CredenzaContent,
    CredenzaFooter,
    CredenzaHeader,
    CredenzaTitle,
    Field,
    FieldLabel,
    Item,
    ItemContent,
    ItemDescription,
    Text,
} from '@posthog/quill'

import { PropertyDefinition } from './materializedColumnsLogic'
import { useAssignSlotForm } from './useAssignSlotForm'

/** Quill version of `CreateSlotModal`, with the same property pick and submit. */
export function QuillCreateSlotModal(): JSX.Element {
    const inputId = useId()
    const {
        availableProperties,
        availablePropertiesLoading,
        filteredProperties,
        selectedProperty,
        setSelectedPropertyId,
        searchTerm,
        setSearchTerm,
        isSubmitting,
        handleSubmit,
        close,
    } = useAssignSlotForm()

    return (
        <Credenza
            open
            onOpenChange={(open) => {
                if (!open) {
                    close()
                }
            }}
        >
            <CredenzaContent className="sm:max-w-144">
                <CredenzaHeader>
                    <CredenzaTitle>Assign Materialized Column Slot</CredenzaTitle>
                </CredenzaHeader>
                <CredenzaBody viewportClassName="flex flex-col gap-4">
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        Select a property to queue for materialization. The slot starts in <strong>PENDING</strong>{' '}
                        state; the next weekly backfill cycle will assign it a column, run the historical backfill, and
                        transition it to <strong>READY</strong>. Until then HogQL falls back to JSON extraction for this
                        property.
                    </Text>

                    <Field>
                        <FieldLabel htmlFor={inputId}>Property to materialize</FieldLabel>
                        <Combobox<PropertyDefinition>
                            items={filteredProperties}
                            value={selectedProperty ?? null}
                            onValueChange={(property) => {
                                setSelectedPropertyId(property?.id ?? null)
                                setSearchTerm('')
                            }}
                            inputValue={selectedProperty ? selectedProperty.name : searchTerm}
                            onInputValueChange={(value: string, { reason }) => {
                                // Picking an option also writes its label into the input, which is not a search.
                                if (reason !== 'input-change' && reason !== 'input-clear') {
                                    return
                                }
                                // Typing over a picked property starts a new search, so the pick is cleared.
                                setSelectedPropertyId(null)
                                setSearchTerm(value)
                            }}
                            itemToStringLabel={(property: PropertyDefinition) => property.name}
                            isItemEqualToValue={(a: PropertyDefinition, b: PropertyDefinition) => a.id === b.id}
                            filter={null}
                        >
                            <ComboboxInput
                                id={inputId}
                                className="w-full"
                                placeholder="Search properties..."
                                showClear={!!selectedProperty}
                                autoFocus
                            />
                            {/* The popup sizes to its content by default, so it matches the full-width field instead. */}
                            <ComboboxContent className="w-(--anchor-width) max-w-(--anchor-width)">
                                <ComboboxEmpty>
                                    {availablePropertiesLoading
                                        ? 'Loading properties...'
                                        : searchTerm
                                          ? 'No properties match your search'
                                          : 'No properties available'}
                                </ComboboxEmpty>
                                <ComboboxList>
                                    {(property: PropertyDefinition) => (
                                        <ComboboxItem key={property.id} value={property}>
                                            <span className="flex min-w-0 items-center gap-2">
                                                <span className="truncate">{property.name}</span>
                                                <Badge>{property.property_type}</Badge>
                                            </span>
                                        </ComboboxItem>
                                    )}
                                </ComboboxList>
                            </ComboboxContent>
                        </Combobox>
                    </Field>

                    {availableProperties.length === 0 && !availablePropertiesLoading && (
                        <Item tone="warning" size="sm">
                            <ItemContent>
                                <ItemDescription>
                                    No properties available for materialization. All eligible properties have either
                                    been materialized or don't have a property_type set.
                                </ItemDescription>
                            </ItemContent>
                        </Item>
                    )}
                </CredenzaBody>
                <CredenzaFooter>
                    <Button variant="outline" onClick={close}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={handleSubmit}
                        loading={isSubmitting}
                        disabledReason={!selectedProperty ? 'Please select a property' : undefined}
                    >
                        Queue for materialization
                    </Button>
                </CredenzaFooter>
            </CredenzaContent>
        </Credenza>
    )
}
