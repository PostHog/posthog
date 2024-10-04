import { hide } from '@floating-ui/react'
import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ActionPopoverInfo } from 'lib/components/DefinitionPopover/ActionPopoverInfo'
import { CohortPopoverInfo } from 'lib/components/DefinitionPopover/CohortPopoverInfo'
import { DefinitionPopover } from 'lib/components/DefinitionPopover/DefinitionPopover'
import { definitionPopoverLogic, DefinitionPopoverState } from 'lib/components/DefinitionPopover/definitionPopoverLogic'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import {
    SimpleOption,
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
} from 'lib/components/TaxonomicFilter/types'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { Popover } from 'lib/lemon-ui/Popover'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { CORE_FILTER_DEFINITIONS_BY_GROUP, isCoreFilter } from 'lib/taxonomy'
import { useEffect, useMemo } from 'react'
import { DataWarehouseTableForInsight } from 'scenes/data-warehouse/types'

import { ActionType, CohortType, EventDefinition, PropertyDefinition } from '~/types'

import { taxonomicFilterLogic } from '../TaxonomicFilter/taxonomicFilterLogic'
import { TZLabel } from '../TZLabel'

export function VerifiedDefinitionCheckbox({
    verified,
    isProperty,
    onChange,
    compact = false,
}: {
    verified: boolean
    isProperty: boolean
    onChange: (nextVerified: boolean) => void
    compact?: boolean
}): JSX.Element {
    const copy = isProperty
        ? 'Verifying a property is a signal to collaborators that this property should be used in favor of similar properties.'
        : 'Verified events are prioritized in filters and other selection components. Verifying an event is a signal to collaborators that this event should be used in favor of similar events.'

    return (
        <>
            {!compact && <p>{copy}</p>}

            <LemonSwitch
                checked={verified}
                onChange={() => {
                    onChange(!verified)
                }}
                bordered
                label={
                    <>
                        Mark as verified {isProperty ? 'property' : 'event'}
                        {compact && (
                            <Tooltip title={copy}>
                                <IconInfo className="ml-2 text-muted text-xl shrink-0" />
                            </Tooltip>
                        )}
                    </>
                }
            />
        </>
    )
}

function DefinitionView({ group }: { group: TaxonomicFilterGroup }): JSX.Element {
    const {
        definition,
        localDefinition,
        type,
        hasTaxonomyFeatures,
        isAction,
        isEvent,
        isCohort,
        isDataWarehouse,
        isDataWarehousePersonProperty,
        isProperty,
        hasSentAs,
    } = useValues(definitionPopoverLogic)

    const { setLocalDefinition } = useActions(definitionPopoverLogic)
    const { selectedItemMeta } = useValues(taxonomicFilterLogic)
    const { selectItem } = useActions(taxonomicFilterLogic)

    // Use effect here to make definition view stateful. TaxonomicFilterLogic won't mount within definitionPopoverLogic
    useEffect(() => {
        if (selectedItemMeta && definition.name == selectedItemMeta.id) {
            setLocalDefinition(selectedItemMeta)
        }
    }, [definition])

    const hasSentAsLabel = useMemo(() => {
        const _definition = definition as PropertyDefinition

        if (!_definition) {
            return null
        }

        if (isDataWarehousePersonProperty) {
            return _definition.id
        }

        if (_definition.name !== '') {
            return _definition.name
        }

        return <i>(empty string)</i>
    }, [isDataWarehousePersonProperty, definition, isProperty])

    if (!definition) {
        return <></>
    }

    const description: string | JSX.Element | undefined | null =
        (definition && 'description' in definition && definition?.description) ||
        (definition?.name && CORE_FILTER_DEFINITIONS_BY_GROUP[group.type]?.[definition.name]?.description)

    const sharedComponents = (
        <>
            {description ? (
                <DefinitionPopover.Description description={description} />
            ) : (
                <DefinitionPopover.DescriptionEmpty />
            )}
            <DefinitionPopover.Example value={group?.getValue?.(definition)?.toString()} />
            {hasTaxonomyFeatures && definition && 'tags' in definition && !!definition.tags?.length && (
                <ObjectTags
                    className="definition-popover-tags"
                    tags={definition.tags}
                    style={{ marginBottom: 4 }}
                    staticOnly
                />
            )}
            <DefinitionPopover.TimeMeta
                createdAt={(definition && 'created_at' in definition && definition.created_at) || undefined}
                createdBy={(definition && 'created_by' in definition && definition.created_by) || undefined}
                updatedAt={(definition && 'updated_at' in definition && definition.updated_at) || undefined}
                updatedBy={(definition && 'updated_by' in definition && definition.updated_by) || undefined}
            />
            <LemonDivider className="DefinitionPopover my-4" />
        </>
    )

    // Things start to get different here
    if (isEvent) {
        const _definition = definition as EventDefinition
        return (
            <>
                {sharedComponents}
                <DefinitionPopover.Grid cols={2}>
                    <DefinitionPopover.Card
                        title="First seen"
                        value={_definition.created_at && <TZLabel time={_definition.created_at} />}
                    />
                    <DefinitionPopover.Card
                        title="Last seen"
                        value={_definition.last_seen_at && <TZLabel time={_definition.last_seen_at} />}
                    />
                </DefinitionPopover.Grid>

                {hasSentAs ? (
                    <>
                        <DefinitionPopover.HorizontalLine />
                        <DefinitionPopover.Section>
                            <DefinitionPopover.Card
                                title="Sent as"
                                value={<span className="font-mono text-xs">{_definition.name}</span>}
                            />
                        </DefinitionPopover.Section>
                    </>
                ) : null}
            </>
        )
    }
    if (isAction) {
        const _definition = definition as ActionType
        return (
            <>
                {sharedComponents}
                <ActionPopoverInfo entity={_definition} />
                {(_definition?.steps?.length || 0) > 0 && <LemonDivider className="DefinitionPopover my-4" />}
                <DefinitionPopover.Grid cols={2}>
                    <DefinitionPopover.Card
                        title="First seen"
                        value={_definition.created_at && <TZLabel time={_definition.created_at} />}
                    />
                </DefinitionPopover.Grid>
            </>
        )
    }

    if (isProperty) {
        const _definition = definition as PropertyDefinition

        return (
            <>
                {sharedComponents}
                <DefinitionPopover.Grid cols={2}>
                    <DefinitionPopover.Card title="Property Type" value={_definition.property_type ?? '-'} />
                </DefinitionPopover.Grid>
                {hasSentAs ? (
                    <>
                        <DefinitionPopover.HorizontalLine />
                        <DefinitionPopover.Grid cols={2}>
                            <DefinitionPopover.Card
                                title={isDataWarehousePersonProperty ? 'Table' : 'Sent as'}
                                value={
                                    <span
                                        className="truncate text-mono text-xs"
                                        title={
                                            isDataWarehousePersonProperty
                                                ? _definition.id
                                                : _definition.name ?? undefined
                                        }
                                    >
                                        {hasSentAsLabel}
                                    </span>
                                }
                            />
                        </DefinitionPopover.Grid>
                    </>
                ) : null}
            </>
        )
    }
    if (isCohort) {
        const _definition = definition as CohortType
        if (type === TaxonomicFilterGroupType.CohortsWithAllUsers) {
            return (
                <>
                    {sharedComponents}
                    <DefinitionPopover.Grid cols={2}>
                        <DefinitionPopover.Card title="Persons" value={_definition.count ?? 0} />
                        <DefinitionPopover.Card
                            title="Last calculated"
                            value={_definition.last_calculation && <TZLabel time={_definition.last_calculation} />}
                        />
                    </DefinitionPopover.Grid>
                </>
            )
        }
        if (!_definition.is_static) {
            return (
                <>
                    {sharedComponents}
                    <DefinitionPopover.Grid cols={2}>
                        <DefinitionPopover.Card title="Persons" value={_definition.count ?? 0} />
                        <DefinitionPopover.Card
                            title="Last calculated"
                            value={_definition.last_calculation && <TZLabel time={_definition.last_calculation} />}
                        />
                    </DefinitionPopover.Grid>
                    <CohortPopoverInfo cohort={_definition} />
                </>
            )
        }
        return (
            <>
                {sharedComponents}
                <DefinitionPopover.Grid cols={2}>
                    <DefinitionPopover.Card title="Persons" value={_definition.count ?? 0} />
                    <DefinitionPopover.Card
                        title="Last calculated"
                        value={_definition.last_calculation && <TZLabel time={_definition.last_calculation} />}
                    />
                </DefinitionPopover.Grid>
            </>
        )
    }
    if (group.type === TaxonomicFilterGroupType.Elements) {
        const _definition = definition as SimpleOption
        return (
            <>
                {sharedComponents}
                <DefinitionPopover.Section>
                    <DefinitionPopover.Card
                        title="Sent as"
                        value={<span className="text-xs font-mono">{_definition.name}</span>}
                    />
                </DefinitionPopover.Section>
            </>
        )
    }
    if (isDataWarehouse) {
        const _definition = definition as DataWarehouseTableForInsight
        const columnOptions = Object.values(_definition.fields).map((column) => ({
            label: column.name + ' (' + column.type + ')',
            value: column.name,
        }))
        const itemValue = localDefinition ? group?.getValue?.(localDefinition) : null

        return (
            <form className="definition-popover-data-warehouse-schema-form">
                <div className="flex flex-col justify-between gap-4">
                    <DefinitionPopover.Section>
                        <label className="definition-popover-edit-form-label" htmlFor="ID Field">
                            <span className="label-text">ID field</span>
                        </label>
                        <LemonSelect
                            value={'id_field' in localDefinition ? localDefinition.id_field : undefined}
                            options={columnOptions}
                            onChange={(value) => setLocalDefinition({ id_field: value })}
                        />

                        <label className="definition-popover-edit-form-label" htmlFor="Distinct Id Field">
                            <span className="label-text">Distinct ID field</span>
                        </label>
                        <LemonSelect
                            value={
                                'distinct_id_field' in localDefinition ? localDefinition.distinct_id_field : undefined
                            }
                            options={columnOptions}
                            onChange={(value) => setLocalDefinition({ distinct_id_field: value })}
                        />

                        <label className="definition-popover-edit-form-label" htmlFor="Timestamp Field">
                            <span className="label-text">Timestamp field</span>
                        </label>
                        <LemonSelect
                            value={
                                ('timestamp_field' in localDefinition && localDefinition.timestamp_field) || undefined
                            }
                            options={columnOptions}
                            onChange={(value) => setLocalDefinition({ timestamp_field: value })}
                        />
                    </DefinitionPopover.Section>
                    <div className="flex justify-end">
                        <LemonButton
                            onClick={() => {
                                selectItem(group, itemValue ?? null, localDefinition)
                            }}
                            disabledReason={
                                'id_field' in localDefinition &&
                                localDefinition.id_field &&
                                'timestamp_field' in localDefinition &&
                                localDefinition.timestamp_field &&
                                'distinct_id_field' in localDefinition &&
                                localDefinition.distinct_id_field
                                    ? null
                                    : 'Field mappings must be specified'
                            }
                            type="primary"
                        >
                            Select
                        </LemonButton>
                    </div>
                </div>
            </form>
        )
    }
    return <></>
}

function DefinitionEdit(): JSX.Element {
    const {
        definition,
        localDefinition,
        definitionLoading,
        singularType,
        hasTaxonomyFeatures,
        isViewable,
        hideView,
        type,
        dirty,
        viewFullDetailUrl,
        isProperty,
    } = useValues(definitionPopoverLogic)
    const { setLocalDefinition, handleCancel, handleSave } = useActions(definitionPopoverLogic)

    if (!definition || !hasTaxonomyFeatures) {
        return <></>
    }

    return (
        <>
            <LemonDivider className="DefinitionPopover my-4" />
            <form className="definition-popover-edit-form">
                {definition && 'description' in localDefinition && (
                    <>
                        <label className="definition-popover-edit-form-label" htmlFor="description">
                            <span className="label-text">Description</span>
                            <span className="text-muted-alt">(optional)</span>
                        </label>
                        <LemonTextArea
                            id="description"
                            className="definition-popover-edit-form-value"
                            autoFocus
                            placeholder={`Add a description for this ${singularType}.`}
                            value={localDefinition.description || ''}
                            onChange={(value) => setLocalDefinition({ description: value })}
                            minRows={3}
                            maxRows={4}
                            data-attr="definition-popover-edit-description"
                        />
                    </>
                )}
                {definition && 'tags' in localDefinition && (
                    <>
                        <label className="definition-popover-edit-form-label" htmlFor="description">
                            <span className="label-text">Tags</span>
                            <span className="text-muted-alt">(optional)</span>
                        </label>
                        <div className="definition-popover-tags">
                            <ObjectTags
                                className="definition-popover-edit-form-value"
                                tags={localDefinition.tags || []}
                                onChange={(tags) => setLocalDefinition({ tags })}
                                saving={false}
                            />
                        </div>
                    </>
                )}
                {definition && definition.name && !isCoreFilter(definition.name) && 'verified' in localDefinition && (
                    <VerifiedDefinitionCheckbox
                        verified={!!localDefinition.verified}
                        isProperty={isProperty}
                        onChange={(nextVerified) => {
                            setLocalDefinition({ verified: nextVerified })
                        }}
                        compact
                    />
                )}
                <LemonDivider className="DefinitionPopover mt-0" />
                <div className="flex items-center justify-between gap-2 click-outside-block">
                    {!hideView && isViewable && type !== TaxonomicFilterGroupType.Events ? (
                        <LemonButton
                            sideIcon={<IconOpenInNew style={{ marginLeft: 4, fontSize: '1rem' }} />}
                            disabledReason={definitionLoading ? 'Loading…' : undefined}
                            type="secondary"
                            size="small"
                            to={viewFullDetailUrl}
                            targetBlank
                        >
                            More options
                        </LemonButton>
                    ) : (
                        <div className="flex-1" />
                    )}
                    <div className="flex items-center">
                        <LemonButton
                            onClick={handleCancel}
                            className=" mr-2"
                            disabledReason={definitionLoading ? 'Loading…' : undefined}
                            type="secondary"
                            size="small"
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={handleSave}
                            disabledReason={!dirty ? 'No changes to save' : undefined}
                            loading={definitionLoading}
                            size="small"
                        >
                            Save
                        </LemonButton>
                    </div>
                </div>
            </form>
        </>
    )
}

interface ControlledDefinitionPopoverContentsProps {
    visible: boolean
    item: TaxonomicDefinitionTypes
    group: TaxonomicFilterGroup
    highlightedItemElement: HTMLDivElement | null
}

export function ControlledDefinitionPopover({
    visible,
    item,
    group,
    highlightedItemElement,
}: ControlledDefinitionPopoverContentsProps): JSX.Element | null {
    const { state, singularType, definition } = useValues(definitionPopoverLogic)
    const { setDefinition } = useActions(definitionPopoverLogic)

    const icon = group.getIcon?.(definition || item)

    // Must use `useEffect` here to hydrate popover card with the newest item, since lifecycle of `ItemPopover` is controlled
    // independently by `infiniteListLogic`
    useEffect(() => {
        setDefinition(item)
    }, [item])

    // Supports all types specified in selectedItemHasPopover
    const value = group.getValue?.(item)

    if (!value || !item) {
        return null
    }

    return (
        <Popover
            visible={visible}
            referenceElement={highlightedItemElement}
            className="click-outside-block hotkey-block"
            overlay={
                <DefinitionPopover.Wrapper>
                    <DefinitionPopover.Header
                        title={
                            <PropertyKeyInfo
                                value={item.name ?? ''}
                                type={group.type}
                                disablePopover
                                disableIcon={!!icon}
                                ellipsis={false}
                            />
                        }
                        headerTitle={group.getPopoverHeader?.(item)}
                        editHeaderTitle={`Edit ${singularType}`}
                        icon={icon}
                    />
                    {state === DefinitionPopoverState.Edit ? <DefinitionEdit /> : <DefinitionView group={group} />}
                </DefinitionPopover.Wrapper>
            }
            placement="right"
            fallbackPlacements={['left']}
            middleware={[hide()]} // Hide the definition popover when the reference is off-screen
        />
    )
}
