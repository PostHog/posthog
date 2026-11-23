import { Field as KeaField } from 'kea-forms'

import { IconPlus, IconTrash } from '@posthog/icons'
import {
    Button,
    Field,
    FieldError,
    Input,
    Label,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

import type { DataColorToken } from 'lib/colors'

import { QuillOptionColorSwatch } from 'products/customer_analytics/frontend/components/QuillOptionColorSwatch'
import type { CustomPropertyOptionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { OPTION_COLOR_TOKENS } from './customPropertyTypes'

export interface QuillCustomPropertyOptionsEditorProps {
    options: CustomPropertyOptionApi[]
    onColorChange: (index: number, colorToken: DataColorToken) => void
    onRemove: (index: number) => void
    onAdd: () => void
}

export function QuillCustomPropertyOptionsEditor({
    options,
    onColorChange,
    onRemove,
    onAdd,
}: QuillCustomPropertyOptionsEditorProps): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <Label>Options</Label>
            {options.map((option, index) => (
                <div key={option.id ?? index} className="flex items-start gap-2">
                    <Select
                        value={option.color as DataColorToken}
                        onValueChange={(colorToken: DataColorToken | null) => {
                            if (colorToken) {
                                onColorChange(index, colorToken)
                            }
                        }}
                    >
                        <SelectTrigger aria-label="Option color">
                            <SelectValue>
                                {(colorToken: DataColorToken) => <QuillOptionColorSwatch colorToken={colorToken} />}
                            </SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                            {OPTION_COLOR_TOKENS.map((colorToken) => (
                                <SelectItem key={colorToken} value={colorToken} aria-label={colorToken}>
                                    <QuillOptionColorSwatch colorToken={colorToken} />
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                    <div className="min-w-0 flex-1">
                        <KeaField name={['options', index, 'label']} noStyle>
                            {({ id, value, onChange, error }) => (
                                <Field data-invalid={error ? true : undefined}>
                                    <Input
                                        id={id}
                                        value={value ?? ''}
                                        onChange={(event) => onChange(event.target.value)}
                                        placeholder="Option label"
                                        aria-label="Option label"
                                    />
                                    {error && <FieldError>{error}</FieldError>}
                                </Field>
                            )}
                        </KeaField>
                    </div>
                    <Button
                        size="icon"
                        aria-label="Remove option"
                        tooltip="Remove option"
                        onClick={() => onRemove(index)}
                    >
                        <IconTrash />
                    </Button>
                </div>
            ))}
            <div>
                <Button variant="outline" onClick={onAdd}>
                    <IconPlus />
                    Add option
                </Button>
            </div>
        </div>
    )
}
