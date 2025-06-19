import { hide } from '@floating-ui/react'
import { IconBadge, IconDashboard, IconEye, IconGraph, IconHide, IconInfo } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSegmentedButton, LemonSelect, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ActionPopoverInfo } from 'lib/components/DefinitionPopover/ActionPopoverInfo'
import { CohortPopoverInfo } from 'lib/components/DefinitionPopover/CohortPopoverInfo'
import { DefinitionPopover } from 'lib/components/DefinitionPopover/DefinitionPopover'
import { definitionPopoverLogic, DefinitionPopoverState } from 'lib/components/DefinitionPopover/definitionPopoverLogic'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import {
    DataWarehousePopoverField,
    SimpleOption,
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
} from 'lib/components/TaxonomicFilter/types'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { Popover } from 'lib/lemon-ui/Popover'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'
import { Fragment, useEffect, useMemo } from 'react'
import { DataWarehouseTableForInsight } from 'scenes/data-warehouse/types'
import { MaxContextOption, MaxDashboardContext, MaxInsightContext } from 'scenes/max/maxTypes'

import { isCoreFilter } from '~/taxonomy/helpers'
import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'
import {
    ActionType,
    CohortType,
    EventDefinition,
    PropertyDefinition,
    PropertyDefinitionVerificationStatus,
} from '~/types'

import { HogQLDropdown } from '../HogQLDropdown/HogQLDropdown'
import { taxonomicFilterLogic } from '../TaxonomicFilter/taxonomicFilterLogic'
import { TZLabel } from '../TZLabel'

export function PropertyStatusControl({
    verified,
    hidden,
    showHiddenOption,
    allowVerification,
    onChange,
    compact = false,
    isProperty,
}: {
    verified: boolean
    hidden: boolean
    showHiddenOption: boolean
    allowVerification: boolean
    onChange: (status: { verified: boolean; hidden: boolean }) => void
    compact?: boolean
    isProperty: boolean
}): JSX.Element {
    const definitionType = isProperty ? 'property' : 'event'
    const copy = {
        verified: `Prioritize this ${definitionType} in filters and other selection components to signal to collaborators that this ${definitionType} should be used in favor of similar ${
            definitionType === 'property' ? 'properties' : `${definitionType}s`
        }.`,
        visible: `${
            definitionType.charAt(0).toUpperCase() + definitionType.slice(1)
        } is available for use but has not been verified by the team.`,
        hidden: `Hide this ${definitionType} from filters and other selection components by default. Use this for deprecated or irrelevant ${definitionType}s.`,
    }

    const verifiedDisabledCorePropCopy = `Core PostHog ${definitionType}s are inherently treated as if verified, but they can still be hidden.`

    const currentStatus: PropertyDefinitionVerificationStatus = hidden ? 'hidden' : verified ? 'verified' : 'visible'

    return (
        <>
            <LemonSegmentedButton
                value={currentStatus}
                onChange={(value) => {
                    const status = value as PropertyDefinitionVerificationStatus
                    onChange({
                        verified: status === 'verified',
                        hidden: status === 'hidden',
                    })
                }}
                options={[
                    {
                        value: 'verified',
                        label: 'Verified',
                        tooltip: allowVerification ? copy.verified : undefined,
                        icon: <IconBadge />,
                        disabledReason: !allowVerification ? verifiedDisabledCorePropCopy : undefined,
                    },
                    {
                        value: 'visible',
                        label: 'Visible',
                        tooltip: copy.visible,
                        icon: <IconEye />,
                    },
                    ...(showHiddenOption
                        ? [
                              {
                                  value: 'hidden',
                                  label: 'Hidden',
                                  tooltip: copy.hidden,
                                  icon: <IconHide />,
                              },
                          ]
                        : []),
                ]}
            />
            {!compact && <p className="italic">{copy[currentStatus]}</p>}
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
        isVirtual,
    } = useValues(definitionPopoverLogic)

    const { setLocalDefinition } = useActions(definitionPopoverLogic)
    const { selectedItemMeta, dataWarehousePopoverFields } = useValues(taxonomicFilterLogic)
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
                {_definition.verified && (
                    <div className="mb-4">
                        <Tooltip title="This property is verified by the team. It is prioritized in filters and other selection components.">
                            <LemonTag type="success">
                                <IconBadge /> Verified
                            </LemonTag>
                        </Tooltip>
                    </div>
                )}
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
                {isVirtual ? (
                    <>
                        <DefinitionPopover.HorizontalLine />
                        <DefinitionPopover.Grid cols={2}>
                            <DefinitionPopover.Card
                                title="Virtual"
                                value={
                                    <span className="text-xs">
                                        Virtual properties are computed from other properties, and are not sent
                                        directly.
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
    if (group.type === TaxonomicFilterGroupType.EventMetadata) {
        const _definition = definition as PropertyDefinition
        return (
            <>
                {sharedComponents}
                <DefinitionPopover.Grid cols={2}>
                    <DefinitionPopover.Card title="Type" value={_definition.property_type ?? '-'} />
                </DefinitionPopover.Grid>
                <LemonDivider className="DefinitionPopover my-4" />
                <DefinitionPopover.Section>
                    <DefinitionPopover.Card
                        title="Sent as"
                        value={<span className="text-xs font-mono">{_definition.id}</span>}
                    />
                </DefinitionPopover.Section>
            </>
        )
    }
    if (group.type === TaxonomicFilterGroupType.MaxAIContext) {
        const _definition = definition as MaxContextOption
        if (_definition.value !== 'current_page') {
            return <></>
        }
        return (
            <>
                {sharedComponents}
                {_definition.items?.dashboards && _definition.items.dashboards.length > 0 && (
                    <DefinitionPopover.Section>
                        <DefinitionPopover.Card
                            title="Dashboard"
                            value={
                                <div className="flex flex-wrap gap-1">
                                    {_definition.items.dashboards.map((dashboard: MaxDashboardContext) => (
                                        <LemonTag
                                            key={dashboard.id}
                                            size="small"
                                            icon={<IconDashboard />}
                                            className="text-xs"
                                        >
                                            {dashboard.name || `Dashboard ${dashboard.id}`}
                                        </LemonTag>
                                    ))}
                                </div>
                            }
                        />
                    </DefinitionPopover.Section>
                )}
                {_definition.items?.insights && _definition.items.insights.length > 0 && (
                    <>
                        <LemonDivider className="DefinitionPopover my-4" />
                        <DefinitionPopover.Section>
                            <DefinitionPopover.Card
                                title="Insights"
                                value={
                                    <div className="flex flex-wrap gap-1">
                                        {_definition.items.insights.map((insight: MaxInsightContext) => (
                                            <LemonTag
                                                key={insight.id}
                                                size="small"
                                                icon={<IconGraph />}
                                                className="text-xs"
                                            >
                                                {insight.name || `Insight ${insight.id}`}
                                            </LemonTag>
                                        ))}
                                    </div>
                                }
                            />
                        </DefinitionPopover.Section>
                    </>
                )}
            </>
        )
    }
    if (isDataWarehouse) {
        const _definition = definition as DataWarehouseTableForInsight
        const columnOptions = Object.values(_definition.fields).map((column) => ({
            label: column.name + ' (' + column.type + ')',
            value: column.name,
            type: column.type,
        }))
        const hogqlOption = { label: 'SQL Expression', value: '' }
        const itemValue = localDefinition ? group?.getValue?.(localDefinition) : null

        const isUsingHogQLExpression = (value: string | undefined): boolean => {
            if (value === undefined) {
                return false
            }
            const column = Object.values(_definition.fields ?? {}).find((n) => n.name == value)
            return !column
        }

        return (
            <form className="definition-popover-data-warehouse-schema-form">
                <div className="flex flex-col justify-between gap-4">
                    <DefinitionPopover.Section>
                        {dataWarehousePopoverFields.map(
                            ({
                                key,
                                label,
                                description,
                                allowHogQL,
                                hogQLOnly,
                                tableName,
                                optional,
                                type,
                            }: DataWarehousePopoverField) => {
                                const fieldValue = key in localDefinition ? localDefinition[key] : undefined
                                const isHogQL = isUsingHogQLExpression(fieldValue)

                                return (
                                    <Fragment key={key}>
                                        <label className="definition-popover-edit-form-label" htmlFor={key}>
                                            <span
                                                className={cn('label-text', {
                                                    'font-semibold': !optional,
                                                })}
                                            >
                                                {label}
                                                {!optional && <span className="text-muted">&nbsp;*</span>}
                                            </span>
                                            {description && (
                                                <Tooltip title={description}>
                                                    &nbsp;
                                                    <IconInfo className="ml-1" />
                                                </Tooltip>
                                            )}
                                        </label>
                                        {!hogQLOnly && (
                                            <LemonSelect
                                                fullWidth
                                                allowClear={!!optional}
                                                value={isHogQL ? '' : fieldValue}
                                                options={[
                                                    ...columnOptions.filter((col) => !type || col.type === type),
                                                    ...(allowHogQL ? [hogqlOption] : []),
                                                ]}
                                                onChange={(value: string | null) =>
                                                    setLocalDefinition({ [key]: value })
                                                }
                                            />
                                        )}
                                        {((allowHogQL && isHogQL) || hogQLOnly) && (
                                            <HogQLDropdown
                                                hogQLValue={fieldValue || ''}
                                                tableName={tableName || _definition.name}
                                                onHogQLValueChange={(value) => setLocalDefinition({ [key]: value })}
                                            />
                                        )}
                                    </Fragment>
                                )
                            }
                        )}
                    </DefinitionPopover.Section>
                    <div className="flex justify-end">
                        <LemonButton
                            onClick={() => {
                                selectItem(group, itemValue ?? null, localDefinition, undefined)
                            }}
                            disabledReason={
                                dataWarehousePopoverFields.every(
                                    ({ key, optional }: DataWarehousePopoverField) =>
                                        optional || (key in localDefinition && localDefinition[key])
                                )
                                    ? null
                                    : 'All required field mappings must be specified'
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

    const showHiddenOption = hasTaxonomyFeatures && 'hidden' in localDefinition
    const allowVerification =
        hasTaxonomyFeatures && !isCoreFilter(definition.name || '') && 'verified' in localDefinition

    return (
        <>
            <LemonDivider className="DefinitionPopover my-4" />
            <form className="definition-popover-edit-form">
                {definition && 'description' in localDefinition && (
                    <>
                        <label className="definition-popover-edit-form-label" htmlFor="description">
                            <span className="label-text">Description</span>
                            <span className="text-secondary">(optional)</span>
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
                            <span className="text-secondary">(optional)</span>
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
                {definition && definition.name && (showHiddenOption || allowVerification) && (
                    <div className="mb-4">
                        <PropertyStatusControl
                            isProperty={isProperty}
                            verified={!!localDefinition.verified}
                            hidden={!!(localDefinition as Partial<PropertyDefinition>).hidden}
                            onChange={({ verified, hidden }) => {
                                setLocalDefinition({ verified, hidden } as Partial<PropertyDefinition>)
                            }}
                            compact
                            showHiddenOption={showHiddenOption}
                            allowVerification={allowVerification}
                        />
                    </div>
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
