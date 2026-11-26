import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'

import { CheckTypeEnumApi } from './generated/api.schemas'
import { QuillCheckFormField } from './QuillCheckFormField'
import { QuillCheckNumberInput } from './QuillCheckNumberInput'
import { QuillCustomSqlField } from './QuillCustomSqlField'
import { QuillRelationshipFields } from './QuillRelationshipFields'

export function QuillCheckConfigFields({ checkType }: { checkType: CheckTypeEnumApi }): JSX.Element | null {
    switch (checkType) {
        case CheckTypeEnumApi.AcceptedValues:
            return (
                <QuillCheckFormField name="acceptedValues" label="Allowed values">
                    {({ value, onChange }) => (
                        <TagsCombobox
                            value={((value ?? []) as unknown[]).map(String)}
                            onChange={onChange}
                            placeholder="Add a value"
                            customValueNoun="value"
                            dataAttr="data-quality-check-accepted-values"
                        />
                    )}
                </QuillCheckFormField>
            )
        case CheckTypeEnumApi.Relationships:
            return <QuillRelationshipFields />
        case CheckTypeEnumApi.RowCount:
            return (
                <div className="flex flex-wrap gap-4 *:min-w-40 *:flex-1">
                    <QuillCheckFormField name="rowCountMin" label="Minimum rows" optional>
                        {({ id, value, onChange, invalid }) => (
                            <QuillCheckNumberInput
                                id={id}
                                value={value}
                                onChange={onChange}
                                invalid={invalid}
                                min={0}
                            />
                        )}
                    </QuillCheckFormField>
                    <QuillCheckFormField name="rowCountMax" label="Maximum rows" optional>
                        {({ id, value, onChange, invalid }) => (
                            <QuillCheckNumberInput
                                id={id}
                                value={value}
                                onChange={onChange}
                                invalid={invalid}
                                min={0}
                            />
                        )}
                    </QuillCheckFormField>
                </div>
            )
        case CheckTypeEnumApi.Freshness:
            return (
                <QuillCheckFormField
                    name="maxAgeMinutes"
                    label="Maximum age in minutes"
                    description="The check fails when the newest value in the column is older than this."
                >
                    {({ id, value, onChange, invalid }) => (
                        <QuillCheckNumberInput id={id} value={value} onChange={onChange} invalid={invalid} min={1} />
                    )}
                </QuillCheckFormField>
            )
        case CheckTypeEnumApi.CustomSql:
            return <QuillCustomSqlField />
        default:
            return null
    }
}
