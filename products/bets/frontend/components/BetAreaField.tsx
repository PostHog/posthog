import { useActions, useValues } from 'kea'

import {
    Autocomplete,
    AutocompleteContent,
    AutocompleteInput,
    AutocompleteItem,
    AutocompleteList,
    Field,
    FieldLabel,
} from '@posthog/quill'

import { betFormLogic } from '../logics/betFormLogic'

export function BetAreaField({ id }: { id: string }): JSX.Element {
    const { form, areas } = useValues(betFormLogic({ id }))
    const { change } = useActions(betFormLogic({ id }))
    return (
        <Field>
            <FieldLabel htmlFor="bet-area">Product area (optional)</FieldLabel>
            <Autocomplete
                items={areas}
                value={form.area ?? ''}
                onValueChange={(value: string) => change({ area: value.slice(0, 120) })}
            >
                <AutocompleteInput id="bet-area" placeholder="For example, Checkout" showSearchIcon={false} />
                {areas.length > 0 && (
                    <AutocompleteContent>
                        <AutocompleteList>
                            {(item: string) => (
                                <AutocompleteItem key={item} value={item}>
                                    {item}
                                </AutocompleteItem>
                            )}
                        </AutocompleteList>
                    </AutocompleteContent>
                )}
            </Autocomplete>
        </Field>
    )
}
