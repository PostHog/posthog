import { IconPlus } from '@posthog/icons'
import {
    Autocomplete,
    AutocompleteContent,
    AutocompleteInput,
    AutocompleteItem,
    AutocompleteList,
    Button,
    Text,
} from '@posthog/quill'

import { PropertyValue } from 'lib/components/PropertyFilters/components/PropertyValue'
import { VerticalNestedDND } from 'lib/components/VerticalNestedDND/VerticalNestedDND'
import { QuillSurfaceContext } from 'lib/ui/QuillSurface/quillSurfaceContext'

import { CustomChannelCondition, CustomChannelRule } from '~/queries/schema/schema-general'
import { PropertyFilterType } from '~/types'

import type { ChannelTypeEditorProps } from './CustomChannelTypes'
import {
    combinerOptions,
    createNewChannelTypeCondition,
    createNewChannelTypeRule,
    isNullary,
    keyOptions,
    keyToSessionProperty,
    opOptions,
    opToPropertyOperator,
} from './customChannelTypesUtils'
import { QuillOptionSelect } from './QuillOptionSelect'

export function QuillChannelTypeEditor({
    handleChange,
    initialCustomChannelTypeRules,
    channelTypeOptions,
    isSaveDisabled,
    onSave,
    canEdit,
}: ChannelTypeEditorProps): JSX.Element {
    const channelTypes = channelTypeOptions.map((option) => option.key)
    const editDisabledReason = canEdit ? undefined : 'You need editor access to modify channel types'

    return (
        <VerticalNestedDND<CustomChannelCondition, CustomChannelRule>
            initialItems={initialCustomChannelTypeRules}
            renderContainerItem={(rule, { updateContainerItem }) => {
                return (
                    <div className="flex flex-col gap-2">
                        <div className="flex flex-wrap items-center gap-2">
                            <Text size="xs" render={<span className="m-0" />}>
                                Set Channel type to
                            </Text>
                            <Autocomplete
                                items={channelTypes}
                                value={rule.channel_type}
                                onValueChange={(channelType: string) =>
                                    updateContainerItem({
                                        ...rule,
                                        channel_type: channelType,
                                    })
                                }
                            >
                                <AutocompleteInput
                                    className="min-w-48 flex-1"
                                    showSearchIcon={false}
                                    placeholder="Enter a channel type name"
                                    aria-label="Channel type"
                                    disabled={!canEdit}
                                />
                                <AutocompleteContent>
                                    <AutocompleteList>
                                        {(channelType: string) => (
                                            <AutocompleteItem key={channelType} value={channelType}>
                                                {channelType}
                                            </AutocompleteItem>
                                        )}
                                    </AutocompleteList>
                                </AutocompleteContent>
                            </Autocomplete>
                        </div>
                        {rule.items.length > 0 ? (
                            rule.items.length == 1 ? (
                                <Text size="xs" render={<span className="m-0" />}>
                                    when this condition is met
                                </Text>
                            ) : (
                                <div className="flex flex-wrap items-center gap-2">
                                    <Text size="xs" render={<span className="m-0" />}>
                                        When
                                    </Text>
                                    <QuillOptionSelect
                                        value={rule.combiner}
                                        options={combinerOptions}
                                        onChange={(combiner) => updateContainerItem({ ...rule, combiner })}
                                        disabledReason={editDisabledReason}
                                        ariaLabel="Condition match"
                                    />
                                    <Text size="xs" render={<span className="m-0" />}>
                                        conditions are met
                                    </Text>
                                </div>
                            )
                        ) : null}
                    </div>
                )
            }}
            renderChildItem={(rule, { updateChildItem }) => {
                return (
                    <div className="flex w-full flex-col gap-2">
                        <div className="flex flex-wrap gap-2">
                            <QuillOptionSelect
                                value={rule.key}
                                options={keyOptions}
                                onChange={(key) => updateChildItem({ ...rule, key })}
                                disabledReason={editDisabledReason}
                                ariaLabel="Property"
                            />
                            <QuillOptionSelect
                                value={rule.op}
                                options={opOptions}
                                onChange={(op) => updateChildItem({ ...rule, op })}
                                disabledReason={editDisabledReason}
                                ariaLabel="Operator"
                            />
                        </div>
                        {isNullary(rule.op) ? null : canEdit ? (
                            <QuillSurfaceContext.Provider value={true}>
                                <PropertyValue
                                    key={rule.key}
                                    propertyKey={keyToSessionProperty(rule.key)}
                                    type={PropertyFilterType.Session}
                                    onSet={(propertyValue: any) => {
                                        updateChildItem({ ...rule, value: propertyValue })
                                    }}
                                    operator={opToPropertyOperator[rule.op]}
                                    value={rule.value}
                                    placeholder="Enter a value"
                                />
                            </QuillSurfaceContext.Provider>
                        ) : (
                            <Text size="xs" variant="muted" render={<span className="m-0" />}>
                                {Array.isArray(rule.value) ? rule.value.join(', ') : rule.value}
                            </Text>
                        )}
                    </div>
                )
            }}
            renderAddChildItem={(rule, { onAddChild }) => {
                return canEdit ? (
                    <Button variant="primary" onClick={() => onAddChild(rule.id)}>
                        <IconPlus />
                        Add condition
                    </Button>
                ) : null
            }}
            renderAddContainerItem={({ onAddContainer }) => {
                return canEdit ? (
                    <Button variant="primary" onClick={onAddContainer}>
                        <IconPlus />
                        Add rule
                    </Button>
                ) : null
            }}
            renderAdditionalControls={() => {
                return canEdit ? (
                    <Button
                        variant="primary"
                        onClick={onSave}
                        disabledReason={isSaveDisabled ? 'No changes to save' : undefined}
                    >
                        Save custom channel type rules
                    </Button>
                ) : null
            }}
            createNewContainerItem={createNewChannelTypeRule}
            createNewChildItem={createNewChannelTypeCondition}
            onChange={handleChange}
        />
    )
}
