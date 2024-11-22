import { VerticalNestedDND } from 'lib/lemon-ui/VerticalNestedDND/VerticalNestedDND'
import { CustomChannelCondition, CustomChannelField, CustomChannelOperator, CustomChannelRule } from '~/queries/schema'
import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { useMemo, useRef, useState } from 'react'
import { genericOperatorMap, UnexpectedNeverError, uuid } from 'lib/utils'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'
import isEqual from 'lodash.isequal'
import debounce from 'lodash.debounce'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { PropertyValue } from 'lib/components/PropertyFilters/components/PropertyValue'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect'

const combinerOptions = [
    { label: 'All', value: FilterLogicalOperator.And },
    { label: 'Any', value: FilterLogicalOperator.Or },
]

const keyOptions = [
    {
        label: 'Referring domain',
        value: CustomChannelField.ReferringDomain,
    },
    {
        label: 'UTM Source',
        value: CustomChannelField.UTMSource,
    },
    {
        label: 'UTM Medium',
        value: CustomChannelField.UTMMedium,
    },
    {
        label: 'UTM Campaign',
        value: CustomChannelField.UTMCampaign,
    },
]

const opOptions = Object.values(CustomChannelOperator).map((op) => {
    return {
        label: genericOperatorMap[op],
        value: op,
    }
})

const isNullary = (operator: CustomChannelOperator): boolean => {
    return [CustomChannelOperator.IsSet, CustomChannelOperator.IsNotSet].includes(operator)
}

function opToPropertyOperator(op: CustomChannelOperator): PropertyOperator {
    switch (op) {
        case CustomChannelOperator.Exact:
            return PropertyOperator.Exact
        case CustomChannelOperator.IsNot:
            return PropertyOperator.IsNot
        case CustomChannelOperator.IsSet:
            return PropertyOperator.IsSet
        case CustomChannelOperator.IsNotSet:
            return PropertyOperator.IsNotSet
        case CustomChannelOperator.IContains:
            return PropertyOperator.IContains
        case CustomChannelOperator.NotIContains:
            return PropertyOperator.NotIContains
        case CustomChannelOperator.Regex:
            return PropertyOperator.Regex
        case CustomChannelOperator.NotRegex:
            return PropertyOperator.NotRegex
        default:
            throw new UnexpectedNeverError(op)
    }
}

function keyToSessionproperty(key: CustomChannelField): string {
    switch (key) {
        case CustomChannelField.ReferringDomain:
            return '$entry_referring_domain'
        case CustomChannelField.UTMSource:
            return '$entry_utm_source'
        case CustomChannelField.UTMMedium:
            return '$entry_utm_medium'
        case CustomChannelField.UTMCampaign:
            return '$entry_utm_campaign'
        default:
            throw new UnexpectedNeverError(key)
    }
}

export function ChannelType(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const { reportCustomChannelTypeRulesUpdated } = useActions(eventUsageLogic)

    const savedCustomChannelTypeRules =
        currentTeam?.modifiers?.customChannelTypeRules ?? currentTeam?.default_modifiers?.customChannelTypeRules ?? null
    const [customChannelTypeRules] = useState(() =>
        (savedCustomChannelTypeRules || []).map((rule) => {
            return {
                ...rule,
                id: rule.id || uuid(),
                items: (rule.items || []).map((item) => {
                    return {
                        ...item,
                        id: item.id || uuid(),
                    }
                }),
            }
        })
    )

    const lastSavedRef = useRef<CustomChannelRule[]>(customChannelTypeRules)

    const debouncedHandleChange = useMemo(
        () =>
            debounce(
                function handleChange(rules: CustomChannelRule[]): void {
                    // strip conditions where the value is empty, and strip empty rules
                    rules = rules
                        .map((rule) => {
                            return {
                                ...rule,
                                conditions: rule.items.filter((condition) => condition.value !== ''),
                            }
                        })
                        .filter((rule) => {
                            return rule.conditions.length > 0 && rule.channel_type !== ''
                        })

                    // don't update if the rules are the same as the last saved rules
                    if (isEqual(rules, lastSavedRef.current)) {
                        return
                    }

                    updateCurrentTeam({ modifiers: { ...currentTeam?.modifiers, customChannelTypeRules: rules } })
                    reportCustomChannelTypeRulesUpdated(rules.length)
                },
                500,
                { trailing: true, maxWait: 2000 }
            ),
        [updateCurrentTeam, reportCustomChannelTypeRulesUpdated, currentTeam?.modifiers]
    )

    return (
        <ChannelTypeEditor
            handleChange={debouncedHandleChange}
            initialCustomChannelTypeRules={customChannelTypeRules}
        />
    )
}

export interface ChannelTypeEditorProps {
    handleChange: (rules: CustomChannelRule[]) => void
    initialCustomChannelTypeRules: CustomChannelRule[]
}

export function ChannelTypeEditor({
    handleChange,
    initialCustomChannelTypeRules,
}: ChannelTypeEditorProps): JSX.Element {
    return (
        <VerticalNestedDND<CustomChannelCondition, CustomChannelRule>
            initialItems={initialCustomChannelTypeRules}
            renderContainerItem={(rule, { updateContainerItem }) => {
                return (
                    <div className="flex flex-col">
                        <div>
                            Set Channel type to{' '}
                            <LemonInputSelect
                                mode="single"
                                allowCustomValues={true}
                                value={[rule.channel_type]}
                                onChange={(channelType) =>
                                    updateContainerItem({
                                        ...rule,
                                        channel_type: channelType[0],
                                    })
                                }
                            />
                        </div>
                        <div>
                            {rule.items.length <= 1 ? (
                                'When'
                            ) : (
                                <div>
                                    When{' '}
                                    <LemonSelect
                                        value={rule.combiner}
                                        options={combinerOptions}
                                        onChange={(combiner) => updateContainerItem({ ...rule, combiner })}
                                    />
                                </div>
                            )}
                        </div>
                    </div>
                )
            }}
            renderChildItem={(rule, { updateChildItem }) => {
                return (
                    <div className="w-full space-y-2">
                        <div className="flex flex-row space-x-2">
                            <LemonSelect<CustomChannelField>
                                value={rule.key}
                                options={keyOptions}
                                onChange={(key) => updateChildItem({ ...rule, key })}
                            />
                            <LemonSelect<CustomChannelOperator>
                                value={rule.op}
                                options={opOptions}
                                onChange={(op) => updateChildItem({ ...rule, op })}
                            />
                        </div>
                        {isNullary(rule.op) ? null : (
                            <PropertyValue
                                key={rule.key}
                                propertyKey={keyToSessionproperty(rule.key)}
                                type={PropertyFilterType.Session}
                                onSet={(propertyValue: any) => {
                                    updateChildItem({ ...rule, value: propertyValue })
                                }}
                                operator={opToPropertyOperator(rule.op)}
                                value={rule.value}
                            />
                        )}
                    </div>
                )
            }}
            createNewContainerItem={() => {
                return {
                    id: uuid(),
                    items: [
                        {
                            id: uuid(),
                            key: CustomChannelField.ReferringDomain,
                            op: CustomChannelOperator.Exact,
                            value: [],
                        },
                    ],
                    channel_type: '',
                    combiner: FilterLogicalOperator.And,
                }
            }}
            createNewChildItem={() => {
                return {
                    id: uuid(),
                    key: CustomChannelField.ReferringDomain,
                    op: CustomChannelOperator.Exact,
                    value: '',
                }
            }}
            onChange={handleChange}
        />
    )
}
