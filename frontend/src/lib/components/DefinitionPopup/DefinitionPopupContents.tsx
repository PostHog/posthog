import {
    SimpleOption,
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
} from 'lib/components/TaxonomicFilter/types'
import { BindLogic, Provider, useActions, useValues } from 'kea'
import { definitionPopupLogic, DefinitionPopupState } from 'lib/components/DefinitionPopup/definitionPopupLogic'
import React, { CSSProperties, useEffect, useState } from 'react'
import { isPostHogProp, keyMapping, PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { DefinitionPopup } from 'lib/components/DefinitionPopup/DefinitionPopup'
import { InfoCircleOutlined, LockOutlined } from '@ant-design/icons'
import { Link } from 'lib/components/Link'
import { IconInfo, IconOpenInNew } from 'lib/components/icons'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { ActionType, CohortType, EventDefinition, PropertyDefinition } from '~/types'
import { ActionPopupInfo } from 'lib/components/DefinitionPopup/ActionPopupInfo'
import { CohortPopupInfo } from 'lib/components/DefinitionPopup/CohortPopupInfo'
import { Button, Checkbox, Input, Typography } from 'antd'
import { formatTimeFromNow } from 'lib/components/DefinitionPopup/utils'
import { CSSTransition } from 'react-transition-group'
import { Tooltip } from 'lib/components/Tooltip'
import { humanFriendlyNumber } from 'lib/utils'
import { usePopper } from 'react-popper'
import ReactDOM from 'react-dom'
import { TitleWithIcon } from '../TitleWithIcon'

export const ThirtyDayVolumeTitle = ({ tooltipPlacement }: { tooltipPlacement?: 'top' | 'bottom' }): JSX.Element => (
    <TitleWithIcon
        icon={
            <Tooltip
                title="Estimated event volume in the past 30 days, updated every 24 hours."
                placement={tooltipPlacement}
            >
                <IconInfo />
            </Tooltip>
        }
    >
        30-day volume
    </TitleWithIcon>
)

export const ThirtyDayQueryCountTitle = ({
    tooltipPlacement,
}: {
    tooltipPlacement?: 'top' | 'bottom'
}): JSX.Element => (
    <TitleWithIcon
        icon={
            <Tooltip
                title="Estimated number of queries in which the event was used in the past 30 days, updated once every 24 hours."
                placement={tooltipPlacement}
            >
                <IconInfo />
            </Tooltip>
        }
    >
        30-day query count
    </TitleWithIcon>
)

function TaxonomyIntroductionSection(): JSX.Element {
    const Lock = (): JSX.Element => (
        <div
            style={{
                height: '100%',
                width: '100%',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                color: 'var(--text-muted)',
            }}
        >
            <Tooltip title="Viewing ingestion data requires a premium license">
                <LockOutlined style={{ marginRight: 6, color: 'var(--warning)' }} />
            </Tooltip>
        </div>
    )

    return (
        <>
            <DefinitionPopup.Grid cols={2}>
                <DefinitionPopup.Card title="First seen" value={<Lock />} />
                <DefinitionPopup.Card title="Last seen" value={<Lock />} />
                <DefinitionPopup.Card title={<ThirtyDayVolumeTitle />} value={<Lock />} />
                <DefinitionPopup.Card title={<ThirtyDayQueryCountTitle />} value={<Lock />} />
            </DefinitionPopup.Grid>
            <DefinitionPopup.Section>
                <Link
                    to="https://posthog.com/docs/user-guides/data-management"
                    target="_blank"
                    data-attr="taxonomy-learn-more"
                    style={{ fontWeight: 600, marginTop: 8 }}
                >
                    Learn more about Data Management
                    <IconOpenInNew style={{ marginLeft: 8 }} />
                </Link>
            </DefinitionPopup.Section>
        </>
    )
}

export function VerifiedEventCheckbox({
    verified,
    onChange,
    compact = false,
}: {
    verified: boolean
    onChange: (nextVerified: boolean) => void
    compact?: boolean
}): JSX.Element {
    const copy =
        'Verified events are prioritized in filters and other selection components. Verifying an event is a signal to collaborators that this event should be used in favor of similar events.'

    return (
        <div style={{ border: '1px solid var(--border)', padding: '0.5rem', borderRadius: 'var(--radius)' }}>
            <Checkbox
                checked={verified}
                onChange={() => {
                    onChange(!verified)
                }}
            >
                <span style={{ fontWeight: 600 }}>
                    Verified event
                    {compact && (
                        <Tooltip title={copy}>
                            <InfoCircleOutlined style={{ marginLeft: '0.5rem', color: 'var(--text-muted)' }} />
                        </Tooltip>
                    )}
                </span>
                {!compact && (
                    <div className="text-muted" style={{ marginTop: '0.25rem' }}>
                        {copy}
                    </div>
                )}
            </Checkbox>
        </div>
    )
}

function DefinitionView({ group }: { group: TaxonomicFilterGroup }): JSX.Element {
    const { definition, type, hasTaxonomyFeatures, isAction, isEvent, isCohort, isElement, isProperty } =
        useValues(definitionPopupLogic)

    if (!definition) {
        return <></>
    }

    const sharedComponents = (
        <>
            {hasTaxonomyFeatures &&
                definition &&
                'description' in definition &&
                (hasTaxonomyFeatures && definition.description ? (
                    <DefinitionPopup.Description description={definition.description} />
                ) : (
                    <DefinitionPopup.DescriptionEmpty />
                ))}
            {isElement && definition?.name && (
                <DefinitionPopup.Description description={keyMapping.element[definition.name].description} />
            )}
            <DefinitionPopup.Example value={group?.getValue(definition)?.toString()} />
            {hasTaxonomyFeatures && definition && 'tags' in definition && !!definition.tags?.length && (
                <ObjectTags
                    className="definition-popup-tags"
                    tags={definition.tags}
                    style={{ marginBottom: 4 }}
                    staticOnly
                />
            )}
            <DefinitionPopup.TimeMeta
                createdAt={(definition && 'created_at' in definition && definition.created_at) || undefined}
                createdBy={(definition && 'created_by' in definition && definition.created_by) || undefined}
                updatedAt={(definition && 'updated_at' in definition && definition.updated_at) || undefined}
                updatedBy={(definition && 'updated_by' in definition && definition.updated_by) || undefined}
            />
            <DefinitionPopup.HorizontalLine />
        </>
    )

    // Things start to get different here
    if (isEvent) {
        const _definition = definition as EventDefinition
        return (
            <>
                {sharedComponents}
                {hasTaxonomyFeatures ? (
                    <DefinitionPopup.Grid cols={2}>
                        <DefinitionPopup.Card title="First seen" value={formatTimeFromNow(_definition.created_at)} />
                        <DefinitionPopup.Card title="Last seen" value={formatTimeFromNow(_definition.last_seen_at)} />
                        <DefinitionPopup.Card
                            title={<ThirtyDayVolumeTitle />}
                            value={
                                _definition.volume_30_day == null ? '-' : humanFriendlyNumber(_definition.volume_30_day)
                            }
                        />
                        <DefinitionPopup.Card
                            title={<ThirtyDayQueryCountTitle />}
                            value={
                                _definition.query_usage_30_day == null
                                    ? '-'
                                    : humanFriendlyNumber(_definition.query_usage_30_day)
                            }
                        />
                    </DefinitionPopup.Grid>
                ) : (
                    <TaxonomyIntroductionSection />
                )}
                <DefinitionPopup.HorizontalLine />
                <DefinitionPopup.Section>
                    <DefinitionPopup.Card
                        title="Sent as"
                        value={<span style={{ fontFamily: 'monaco', fontSize: 12 }}>{_definition.name}</span>}
                    />
                </DefinitionPopup.Section>
            </>
        )
    }
    if (isAction) {
        const _definition = definition as ActionType
        return (
            <>
                {sharedComponents}
                <ActionPopupInfo entity={_definition} />
                {(_definition?.steps?.length || 0) > 0 && <DefinitionPopup.HorizontalLine />}
                <DefinitionPopup.Grid cols={2}>
                    <DefinitionPopup.Card title="First seen" value={formatTimeFromNow(_definition.created_at)} />
                </DefinitionPopup.Grid>
            </>
        )
    }
    if (isProperty) {
        const _definition = definition as PropertyDefinition
        return (
            <>
                {sharedComponents}
                <DefinitionPopup.Grid cols={2}>
                    <DefinitionPopup.Card title="First seen" value={formatTimeFromNow(_definition.created_at)} />
                    <DefinitionPopup.Card title="Last seen" value={formatTimeFromNow(_definition.last_seen_at)} />
                    <DefinitionPopup.Card
                        title="30 day volume"
                        value={_definition.volume_30_day == null ? '-' : humanFriendlyNumber(_definition.volume_30_day)}
                    />
                    <DefinitionPopup.Card
                        title="30 day queries"
                        value={
                            _definition.query_usage_30_day == null
                                ? '-'
                                : humanFriendlyNumber(_definition.query_usage_30_day)
                        }
                    />
                </DefinitionPopup.Grid>
                <DefinitionPopup.HorizontalLine />
                <DefinitionPopup.Grid cols={2}>
                    <DefinitionPopup.Card
                        title="Sent as"
                        value={
                            <>
                                <Typography.Text
                                    ellipsis={true}
                                    title={_definition.name ?? undefined} // because Text can cope with undefined but not null ¯\_(ツ)_/¯
                                    style={{ fontFamily: 'monaco', fontSize: 12, maxWidth: '20em' }}
                                >
                                    {_definition.name !== '' ? _definition.name : <i>(empty string)</i>}
                                </Typography.Text>
                            </>
                        }
                    />
                    <DefinitionPopup.Card
                        title={<>&nbsp;</>}
                        value={<DefinitionPopup.Type propertyType={_definition.property_type} />}
                        alignItems={'end'}
                    />
                </DefinitionPopup.Grid>
            </>
        )
    }
    if (isCohort) {
        const _definition = definition as CohortType
        if (type === TaxonomicFilterGroupType.CohortsWithAllUsers) {
            return (
                <>
                    {sharedComponents}
                    <DefinitionPopup.Grid cols={2}>
                        <DefinitionPopup.Card title="Persons" value={_definition.count ?? 0} />
                        <DefinitionPopup.Card
                            title="Last calculated"
                            value={formatTimeFromNow(_definition.last_calculation)}
                        />
                    </DefinitionPopup.Grid>
                </>
            )
        }
        if (!_definition.is_static) {
            return (
                <>
                    {sharedComponents}
                    <DefinitionPopup.Grid cols={2}>
                        <DefinitionPopup.Card title="Persons" value={_definition.count ?? 0} />
                        <DefinitionPopup.Card
                            title="Last calculated"
                            value={formatTimeFromNow(_definition.last_calculation)}
                        />
                    </DefinitionPopup.Grid>
                    {(_definition.groups?.length || 0 > 0) && <DefinitionPopup.HorizontalLine />}
                    <CohortPopupInfo entity={_definition} />
                </>
            )
        }
        return (
            <>
                {sharedComponents}
                <DefinitionPopup.Grid cols={2}>
                    <DefinitionPopup.Card title="Persons" value={_definition.count ?? 0} />
                    <DefinitionPopup.Card
                        title="Last calculated"
                        value={formatTimeFromNow(_definition.last_calculation)}
                    />
                </DefinitionPopup.Grid>
            </>
        )
    }
    if (isElement) {
        const _definition = definition as SimpleOption
        return (
            <>
                {sharedComponents}
                <DefinitionPopup.Section>
                    <DefinitionPopup.Card
                        title="Sent as"
                        value={<span style={{ fontFamily: 'monaco', fontSize: 12 }}>{_definition.name}</span>}
                    />
                </DefinitionPopup.Section>
            </>
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
    } = useValues(definitionPopupLogic)
    const { setLocalDefinition, handleCancel, handleSave } = useActions(definitionPopupLogic)

    if (!definition || !hasTaxonomyFeatures) {
        return <></>
    }

    return (
        <>
            <DefinitionPopup.HorizontalLine />
            <form className="definition-popup-edit-form">
                {definition && 'description' in localDefinition && (
                    <>
                        <label className="definition-popup-edit-form-label" htmlFor="description">
                            <span className="label-text">Description</span>
                            <span className="text-muted-alt">(optional)</span>
                        </label>
                        <Input.TextArea
                            id="description"
                            className="definition-popup-edit-form-value"
                            autoFocus
                            placeholder={`Add a description for this ${singularType}.`}
                            value={localDefinition.description || ''}
                            onChange={(e) => {
                                setLocalDefinition({ description: e.target.value })
                            }}
                            autoSize={{ minRows: 3, maxRows: 4 }}
                            data-attr="definition-popup-edit-description"
                        />
                    </>
                )}
                {definition && 'tags' in localDefinition && (
                    <>
                        <label className="definition-popup-edit-form-label" htmlFor="description">
                            <span className="label-text">Tags</span>
                            <span className="text-muted-alt">(optional)</span>
                        </label>
                        <div className="definition-popup-tags">
                            <ObjectTags
                                className="definition-popup-edit-form-value"
                                tags={localDefinition.tags || []}
                                onChange={(_, tags) => setLocalDefinition({ tags })}
                                saving={false}
                            />
                        </div>
                    </>
                )}
                {definition && definition.name && !isPostHogProp(definition.name) && 'verified' in localDefinition && (
                    <VerifiedEventCheckbox
                        verified={!!localDefinition.verified}
                        onChange={(nextVerified) => {
                            setLocalDefinition({ verified: nextVerified })
                        }}
                        compact
                    />
                )}
                <DefinitionPopup.HorizontalLine style={{ marginTop: 0 }} />
                <div className="definition-popup-edit-form-buttons click-outside-block">
                    {!hideView && isViewable && type !== TaxonomicFilterGroupType.Events ? (
                        <Link target="_blank" to={viewFullDetailUrl}>
                            <Button
                                className="definition-popup-edit-form-buttons-secondary"
                                style={{ color: 'var(--primary)', display: 'flex', alignItems: 'center' }}
                                disabled={definitionLoading}
                            >
                                More options
                                <IconOpenInNew style={{ marginLeft: 4, fontSize: '1rem' }} />
                            </Button>
                        </Link>
                    ) : (
                        <div style={{ flex: 1 }} />
                    )}
                    <div>
                        <Button
                            onClick={handleCancel}
                            className="definition-popup-edit-form-buttons-secondary"
                            style={{ color: 'var(--primary)', marginRight: 8 }}
                            disabled={definitionLoading}
                        >
                            Cancel
                        </Button>
                        <Button
                            type="primary"
                            onClick={handleSave}
                            className="definition-popup-edit-form-buttons-primary"
                            disabled={definitionLoading || !dirty}
                        >
                            Save
                        </Button>
                    </div>
                </div>
            </form>
        </>
    )
}

interface BaseDefinitionPopupContentsProps {
    item: TaxonomicDefinitionTypes
    group: TaxonomicFilterGroup
}

interface ControlledDefinitionPopupContentsProps extends BaseDefinitionPopupContentsProps {
    popper: {
        styles: CSSProperties
        attributes?: Record<string, any>
        forceUpdate: (() => void) | null
        setRef: React.Dispatch<React.SetStateAction<HTMLDivElement | null>>
        ref: HTMLDivElement | null
    }
}

export function ControlledDefinitionPopupContents({
    item,
    group,
    popper,
}: ControlledDefinitionPopupContentsProps): JSX.Element {
    // Supports all types specified in selectedItemHasPopup
    const value = group.getValue?.(item)

    if (!value || !item) {
        return <></>
    }

    const { state, singularType, isElement, definition, onMouseLeave } = useValues(definitionPopupLogic)
    const { setDefinition } = useActions(definitionPopupLogic)
    const icon = group.getIcon?.(definition || item)

    // Must use `useEffect` here to hydrate popup card with newest item, since lifecycle of `ItemPopup` is controlled
    // independently by `infiniteListLogic`
    useEffect(() => {
        setDefinition(item)
    }, [item])

    // Force popper to recalculate position when popup state changes. Keep this independent of logic
    useEffect(() => {
        popper.forceUpdate?.()
    }, [state])

    return (
        <>
            <CSSTransition
                in={state === DefinitionPopupState.Edit}
                timeout={150}
                classNames="definition-popup-overlay-"
                mountOnEnter
                unmountOnExit
            >
                <div
                    className="definition-popup-overlay click-outside-block hotkey-block"
                    // zIndex: 1062 ensures definition popup overlay is between infinite list (1061) and definition popup (1063)
                    // If not in edit mode, bury it.
                    style={{ zIndex: 1062 }}
                    onClick={() => {
                        popper.ref?.focus()
                    }}
                />
            </CSSTransition>
            <div
                className="popper-tooltip click-outside-block hotkey-block Popup Popup__box"
                tabIndex={-1} // Only programmatically focusable
                ref={popper.setRef}
                // zIndex: 1063 ensures it opens above the overlay which is 1062
                style={{
                    ...popper.styles,
                    transition: 'none',
                    zIndex: 1063,
                }}
                {...popper.attributes}
                onMouseLeave={() => {
                    if (state !== DefinitionPopupState.Edit) {
                        onMouseLeave?.()
                    }
                }}
            >
                <DefinitionPopup.Wrapper>
                    <DefinitionPopup.Header
                        title={
                            <PropertyKeyInfo
                                value={item.name ?? ''}
                                type={isElement ? 'element' : undefined}
                                disablePopover
                                disableIcon={!!icon}
                                ellipsis={false}
                            />
                        }
                        headerTitle={group.getPopupHeader?.(item)}
                        editHeaderTitle={`Edit ${singularType}`}
                        icon={icon}
                    />
                    {state === DefinitionPopupState.Edit ? <DefinitionEdit /> : <DefinitionView group={group} />}
                </DefinitionPopup.Wrapper>
            </div>
        </>
    )
}

interface DefinitionPopupContentsProps extends BaseDefinitionPopupContentsProps {
    referenceEl: HTMLElement | null
    children?: React.ReactNode
    updateRemoteItem?: (item: TaxonomicDefinitionTypes) => void
    onMouseLeave?: () => void
    onCancel?: () => void
    onSave?: () => void
    hideView?: boolean
    hideEdit?: boolean
    openDetailInNewTab?: boolean
}

export function DefinitionPopupContents({
    item,
    group,
    referenceEl,
    children,
    updateRemoteItem,
    onMouseLeave,
    onCancel,
    onSave,
    hideView = false,
    hideEdit = false,
    openDetailInNewTab = true,
}: DefinitionPopupContentsProps): JSX.Element {
    const [popperElement, setPopperElement] = useState<HTMLDivElement | null>(null)

    const { styles, attributes, forceUpdate } = usePopper(referenceEl, popperElement, {
        placement: 'right',
        modifiers: [
            {
                name: 'offset',
                options: {
                    offset: [0, 10],
                },
            },
            {
                name: 'preventOverflow',
                options: {
                    padding: 10,
                },
            },
        ],
    })

    return (
        <>
            <Provider>
                {ReactDOM.createPortal(
                    <BindLogic
                        logic={definitionPopupLogic}
                        props={{
                            type: group.type,
                            updateRemoteItem,
                            onMouseLeave,
                            onSave,
                            onCancel,
                            hideView,
                            hideEdit,
                            openDetailInNewTab,
                        }}
                    >
                        <ControlledDefinitionPopupContents
                            item={item}
                            group={group}
                            popper={{
                                styles: styles.popper,
                                attributes: attributes.popper,
                                forceUpdate,
                                setRef: setPopperElement,
                                ref: popperElement,
                            }}
                        />
                    </BindLogic>,
                    document.querySelector('body') as HTMLElement
                )}
            </Provider>
            {children}
        </>
    )
}
