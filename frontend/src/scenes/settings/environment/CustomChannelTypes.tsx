import { deepEqual as equal } from 'fast-equals'
import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import { PropertyValue } from 'lib/components/PropertyFilters/components/PropertyValue'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { VerticalNestedDND } from 'lib/components/VerticalNestedDND/VerticalNestedDND'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInputSelect, LemonInputSelectOption } from 'lib/lemon-ui/LemonInputSelect'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { Link, LinkPrimitive } from 'lib/lemon-ui/Link'
import { uuid } from 'lib/utils/dom'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import {
    CustomChannelCondition,
    CustomChannelField,
    CustomChannelOperator,
    CustomChannelRule,
    DefaultChannelTypes,
} from '~/queries/schema/schema-general'
import { PropertyFilterType } from '~/types'

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
import { QuillChannelTypeEditor } from './QuillChannelTypeEditor'

const sanitizeCustomChannelTypeRules = (rules?: CustomChannelRule[]): CustomChannelRule[] => {
    return (rules ?? [])
        .map((rule) => {
            return {
                id: rule.id || uuid(),
                channel_type: rule.channel_type,
                combiner: rule.combiner,
                items: (rule.items || [])
                    .map((condition) => ({
                        id: condition.id || uuid(),
                        key: condition.key,
                        op: condition.op,
                        value: condition.value,
                    }))
                    .filter((item) => item.key && item.op && item.value),
            }
        })
        .filter((rule) => rule.channel_type && rule.items.length > 0)
}

export function CustomChannelTypes(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const { reportCustomChannelTypeRulesUpdated } = useActions(eventUsageLogic)

    const [savedCustomChannelTypeRules, setSavedCustomChannelTypeRules] = useState(() =>
        sanitizeCustomChannelTypeRules(
            currentTeam?.modifiers?.customChannelTypeRules ?? currentTeam?.default_modifiers?.customChannelTypeRules
        )
    )

    const [customChannelTypeRules, setCustomChannelTypeRules] = useState(savedCustomChannelTypeRules)

    const channelTypeOptions = useMemo((): LemonInputSelectOption[] => {
        const optionsSet = new Set<string>([
            ...customChannelTypeRules.map((rule) => rule.channel_type),
            ...Object.values(DefaultChannelTypes),
        ])
        return Array.from(optionsSet)
            .filter(Boolean)
            .map((channelType) => ({ label: channelType, key: channelType }))
    }, [customChannelTypeRules])

    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const handleSave = (): void => {
        updateCurrentTeam({
            modifiers: {
                ...currentTeam?.modifiers,
                customChannelTypeRules: sanitizeCustomChannelTypeRules(customChannelTypeRules),
            },
        })
        reportCustomChannelTypeRulesUpdated(customChannelTypeRules.length)
        setSavedCustomChannelTypeRules(customChannelTypeRules)
    }

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-2">
                <Text size="xs" render={<p className="m-0" />}>
                    You can create custom channel types by defining rules that match incoming events. The first matching
                    rule is used, and if no rule matches (or if none are defined) then the{' '}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={
                            <LinkPrimitive
                                to="https://posthog.com/docs/data/channel-type#channel-type-calculation"
                                target="_blank"
                            />
                        }
                    >
                        default channel type
                    </Button>{' '}
                    is used.
                </Text>
                <Text size="xs" render={<p className="m-0" />}>
                    To debug, try the{' '}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={<LinkPrimitive to={urls.sessionAttributionExplorer()} target="_blank" />}
                    >
                        session attribution explorer tool
                    </Button>
                </Text>
                <QuillChannelTypeEditor
                    handleChange={setCustomChannelTypeRules}
                    initialCustomChannelTypeRules={customChannelTypeRules}
                    channelTypeOptions={channelTypeOptions}
                    onSave={handleSave}
                    isSaveDisabled={equal(customChannelTypeRules, savedCustomChannelTypeRules)}
                    canEdit={!restrictedReason}
                />
            </div>
        )
    }

    return (
        <div>
            <p>
                You can create custom channel types by defining rules that match incoming events. The first matching
                rule is used, and if no rule matches (or if none are defined) then the{' '}
                <Link to="https://posthog.com/docs/data/channel-type#channel-type-calculation">
                    default channel type
                </Link>{' '}
                is used.
            </p>
            <p>
                To debug, try the{' '}
                <Link to={urls.sessionAttributionExplorer()} target="_blank">
                    session attribution explorer tool
                </Link>
            </p>
            <ChannelTypeEditor
                handleChange={setCustomChannelTypeRules}
                initialCustomChannelTypeRules={customChannelTypeRules}
                channelTypeOptions={channelTypeOptions}
                onSave={handleSave}
                isSaveDisabled={equal(customChannelTypeRules, savedCustomChannelTypeRules)}
                canEdit={!restrictedReason}
            />
        </div>
    )
}

export interface ChannelTypeEditorProps {
    handleChange: (rules: CustomChannelRule[]) => void
    initialCustomChannelTypeRules: CustomChannelRule[]
    channelTypeOptions: LemonInputSelectOption[]
    isSaveDisabled: boolean
    onSave: () => void
    canEdit: boolean
}

export function ChannelTypeEditor({
    handleChange,
    initialCustomChannelTypeRules,
    channelTypeOptions,
    isSaveDisabled,
    onSave,
    canEdit,
}: ChannelTypeEditorProps): JSX.Element {
    return (
        <VerticalNestedDND<CustomChannelCondition, CustomChannelRule>
            initialItems={initialCustomChannelTypeRules}
            renderContainerItem={(rule, { updateContainerItem }) => {
                return (
                    <div className="flex flex-col deprecated-space-y-2">
                        <div className="flex flex-row items-center deprecated-space-x-2">
                            <span>Set Channel type to</span>
                            <LemonInputSelect
                                className="flex-1"
                                mode="single"
                                allowCustomValues={true}
                                value={[rule.channel_type]}
                                onChange={(channelType) =>
                                    updateContainerItem({
                                        ...rule,
                                        channel_type: channelType[0],
                                    })
                                }
                                options={channelTypeOptions}
                                placeholder="Enter a channel type name"
                                disabled={!canEdit}
                            />
                        </div>
                        {rule.items.length > 0 ? (
                            <div>
                                {rule.items.length == 1 ? (
                                    'when this condition is met'
                                ) : (
                                    <div className="flex flex-row items-center deprecated-space-x-2">
                                        <span>When</span>
                                        <LemonSelect
                                            value={rule.combiner}
                                            options={combinerOptions}
                                            onChange={(combiner) => updateContainerItem({ ...rule, combiner })}
                                            disabledReason={
                                                !canEdit ? 'You need editor access to modify channel types' : undefined
                                            }
                                        />
                                        <span>conditions are met</span>
                                    </div>
                                )}
                            </div>
                        ) : null}
                    </div>
                )
            }}
            renderChildItem={(rule, { updateChildItem }) => {
                return (
                    <div className="w-full deprecated-space-y-2">
                        <div className="flex flex-row deprecated-space-x-2">
                            <LemonSelect<CustomChannelField>
                                value={rule.key}
                                options={keyOptions}
                                onChange={(key) => updateChildItem({ ...rule, key })}
                                disabledReason={!canEdit ? 'You need editor access to modify channel types' : undefined}
                            />
                            <LemonSelect<CustomChannelOperator>
                                value={rule.op}
                                options={opOptions}
                                onChange={(op) => updateChildItem({ ...rule, op })}
                                disabledReason={!canEdit ? 'You need editor access to modify channel types' : undefined}
                            />
                        </div>
                        {isNullary(rule.op) ? null : canEdit ? (
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
                        ) : (
                            <div className="text-muted">
                                {Array.isArray(rule.value) ? rule.value.join(', ') : rule.value}
                            </div>
                        )}
                    </div>
                )
            }}
            renderAddChildItem={(rule, { onAddChild }) => {
                return canEdit ? (
                    <LemonButton type="primary" onClick={() => onAddChild(rule.id)} icon={<IconPlus />}>
                        Add condition
                    </LemonButton>
                ) : null
            }}
            renderAddContainerItem={({ onAddContainer }) => {
                return canEdit ? (
                    <LemonButton type="primary" onClick={onAddContainer} icon={<IconPlus />}>
                        Add rule
                    </LemonButton>
                ) : null
            }}
            renderAdditionalControls={() => {
                return canEdit ? (
                    <LemonButton
                        onClick={onSave}
                        disabledReason={isSaveDisabled ? 'No changes to save' : undefined}
                        type="primary"
                    >
                        Save custom channel type rules
                    </LemonButton>
                ) : null
            }}
            createNewContainerItem={createNewChannelTypeRule}
            createNewChildItem={createNewChannelTypeCondition}
            onChange={handleChange}
        />
    )
}
