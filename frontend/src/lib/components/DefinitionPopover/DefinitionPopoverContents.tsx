import {
    SimpleOption,
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
} from 'lib/components/TaxonomicFilter/types'
import { useActions, useValues } from 'kea'
import { definitionPopoverLogic, DefinitionPopoverState } from 'lib/components/DefinitionPopover/definitionPopoverLogic'
import { useEffect } from 'react'
import { isPostHogProp, keyMapping, PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { DefinitionPopover } from 'lib/components/DefinitionPopover/DefinitionPopover'
import { Link } from 'lib/lemon-ui/Link'
import { IconInfo, IconLock, IconOpenInNew } from 'lib/lemon-ui/icons'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { ActionType, CohortType, EventDefinition, PropertyDefinition } from '~/types'
import { ActionPopoverInfo } from 'lib/components/DefinitionPopover/ActionPopoverInfo'
import { CohortPopoverInfo } from 'lib/components/DefinitionPopover/CohortPopoverInfo'
import { Button, Checkbox, Typography } from 'antd'
import { formatTimeFromNow } from 'lib/components/DefinitionPopover/utils'
import { CSSTransition } from 'react-transition-group'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyNumber } from 'lib/utils'
import { TitleWithIcon } from '../TitleWithIcon'
import { UseFloatingReturn } from '@floating-ui/react'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'

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
        <div className="h-full w-full overflow-hidden text-ellipsis text-muted">
            <Tooltip title="Viewing ingestion data requires a premium license">
                <IconLock className="mr-1 text-warning text-xl shrink-0" />
            </Tooltip>
        </div>
    )

    return (
        <>
            <DefinitionPopover.Grid cols={2}>
                <DefinitionPopover.Card title="First seen" value={<Lock />} />
                <DefinitionPopover.Card title="Last seen" value={<Lock />} />
                <DefinitionPopover.Card title={<ThirtyDayVolumeTitle />} value={<Lock />} />
                <DefinitionPopover.Card title={<ThirtyDayQueryCountTitle />} value={<Lock />} />
            </DefinitionPopover.Grid>
            <DefinitionPopover.Section>
                <Link
                    to="https://posthog.com/docs/user-guides/data-management"
                    target="_blank"
                    data-attr="taxonomy-learn-more"
                    className="mt-2 font-semibold"
                >
                    Learn more about Data Management
                    <IconOpenInNew style={{ marginLeft: 8 }} />
                </Link>
            </DefinitionPopover.Section>
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
        <div className="border p-2 rounded">
            <Checkbox
                checked={verified}
                onChange={() => {
                    onChange(!verified)
                }}
            >
                <span className="font-semibold">
                    Verified event
                    {compact && (
                        <Tooltip title={copy}>
                            <IconInfo className="ml-1 text-muted text-xl shrink-0" />
                        </Tooltip>
                    )}
                </span>
                {!compact && <div className="text-muted mt-1">{copy}</div>}
            </Checkbox>
        </div>
    )
}

function DefinitionView({ group }: { group: TaxonomicFilterGroup }): JSX.Element {
    const { definition, type, hasTaxonomyFeatures, isAction, isEvent, isCohort, isElement, isProperty } =
        useValues(definitionPopoverLogic)

    if (!definition) {
        return <></>
    }

    const sharedComponents = (
        <>
            {hasTaxonomyFeatures &&
                definition &&
                'description' in definition &&
                (hasTaxonomyFeatures && definition.description ? (
                    <DefinitionPopover.Description description={definition.description} />
                ) : (
                    <DefinitionPopover.DescriptionEmpty />
                ))}
            {isElement && definition?.name && (
                <DefinitionPopover.Description description={keyMapping.element[definition.name].description} />
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
            <DefinitionPopover.HorizontalLine />
        </>
    )

    // Things start to get different here
    if (isEvent) {
        const _definition = definition as EventDefinition
        return (
            <>
                {sharedComponents}
                {hasTaxonomyFeatures ? (
                    <DefinitionPopover.Grid cols={2}>
                        <DefinitionPopover.Card title="First seen" value={formatTimeFromNow(_definition.created_at)} />
                        <DefinitionPopover.Card title="Last seen" value={formatTimeFromNow(_definition.last_seen_at)} />
                        <DefinitionPopover.Card
                            title={<ThirtyDayVolumeTitle />}
                            value={
                                _definition.volume_30_day == null ? '-' : humanFriendlyNumber(_definition.volume_30_day)
                            }
                        />
                        <DefinitionPopover.Card
                            title={<ThirtyDayQueryCountTitle />}
                            value={
                                _definition.query_usage_30_day == null
                                    ? '-'
                                    : humanFriendlyNumber(_definition.query_usage_30_day)
                            }
                        />
                    </DefinitionPopover.Grid>
                ) : (
                    <TaxonomyIntroductionSection />
                )}
                <DefinitionPopover.HorizontalLine />
                <DefinitionPopover.Section>
                    <DefinitionPopover.Card
                        title="Sent as"
                        value={<span style={{ fontFamily: 'monaco', fontSize: 12 }}>{_definition.name}</span>}
                    />
                </DefinitionPopover.Section>
            </>
        )
    }
    if (isAction) {
        const _definition = definition as ActionType
        return (
            <>
                {sharedComponents}
                <ActionPopoverInfo entity={_definition} />
                {(_definition?.steps?.length || 0) > 0 && <DefinitionPopover.HorizontalLine />}
                <DefinitionPopover.Grid cols={2}>
                    <DefinitionPopover.Card title="First seen" value={formatTimeFromNow(_definition.created_at)} />
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
                    <DefinitionPopover.Card
                        title="30 day queries"
                        value={
                            _definition.query_usage_30_day == null
                                ? '-'
                                : humanFriendlyNumber(_definition.query_usage_30_day)
                        }
                    />
                    <DefinitionPopover.Card title="Property Type" value={_definition.property_type ?? '-'} />
                </DefinitionPopover.Grid>
                <DefinitionPopover.HorizontalLine />
                <DefinitionPopover.Grid cols={2}>
                    <DefinitionPopover.Card
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
                </DefinitionPopover.Grid>
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
                            value={formatTimeFromNow(_definition.last_calculation)}
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
                            value={formatTimeFromNow(_definition.last_calculation)}
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
                        value={formatTimeFromNow(_definition.last_calculation)}
                    />
                </DefinitionPopover.Grid>
            </>
        )
    }
    if (isElement) {
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
    } = useValues(definitionPopoverLogic)
    const { setLocalDefinition, handleCancel, handleSave } = useActions(definitionPopoverLogic)

    if (!definition || !hasTaxonomyFeatures) {
        return <></>
    }

    return (
        <>
            <DefinitionPopover.HorizontalLine />
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
                <DefinitionPopover.HorizontalLine style={{ marginTop: 0 }} />
                <div className="definition-popover-edit-form-buttons click-outside-block">
                    {!hideView && isViewable && type !== TaxonomicFilterGroupType.Events ? (
                        <Link target="_blank" to={viewFullDetailUrl}>
                            <Button
                                className="definition-popover-edit-form-buttons-secondary"
                                style={{ color: 'var(--primary)', display: 'flex', alignItems: 'center' }}
                                disabled={definitionLoading}
                            >
                                More options
                                <IconOpenInNew style={{ marginLeft: 4, fontSize: '1rem' }} />
                            </Button>
                        </Link>
                    ) : (
                        <div className="flex-1" />
                    )}
                    <div>
                        <Button
                            onClick={handleCancel}
                            className="definition-popover-edit-form-buttons-secondary"
                            style={{ color: 'var(--primary)', marginRight: 8 }}
                            disabled={definitionLoading}
                        >
                            Cancel
                        </Button>
                        <Button
                            type="primary"
                            onClick={handleSave}
                            className="definition-popover-edit-form-buttons-primary"
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

interface BaseDefinitionPopoverContentsProps {
    item: TaxonomicDefinitionTypes
    group: TaxonomicFilterGroup
}

interface ControlledDefinitionPopoverContentsProps extends BaseDefinitionPopoverContentsProps {
    floatingReturn: UseFloatingReturn<HTMLElement>
}

export function ControlledDefinitionPopoverContents({
    item,
    group,
    floatingReturn,
}: ControlledDefinitionPopoverContentsProps): JSX.Element {
    // Supports all types specified in selectedItemHasPopover
    const value = group.getValue?.(item)

    if (!value || !item) {
        return <></>
    }

    const { state, singularType, isElement, definition, onMouseLeave } = useValues(definitionPopoverLogic)
    const { setDefinition } = useActions(definitionPopoverLogic)
    const icon = group.getIcon?.(definition || item)

    // Must use `useEffect` here to hydrate popover card with newest item, since lifecycle of `ItemPopover` is controlled
    // independently by `infiniteListLogic`
    useEffect(() => {
        setDefinition(item)
    }, [item])

    const {
        x,
        y,
        floating: setFloatingRef,
        refs: { floating: floatingRef },
        strategy,
        update,
    } = floatingReturn

    // Force popper to recalculate position when popover state changes. Keep this independent of logic
    useEffect(() => {
        update()
    }, [state])

    return (
        <>
            <CSSTransition timeout={150} classNames="definition-popover-overlay-" mountOnEnter unmountOnExit>
                <div
                    className="definition-popover-overlay click-outside-block hotkey-block"
                    // zIndex: 1062 ensures definition popover overlay is between infinite list (1061) and definition popover (1063)
                    // If not in edit mode, bury it.
                    /* eslint-disable-next-line react/forbid-dom-props */
                    style={{ zIndex: 'var(--z-definition-popover-overlay)' }}
                    onClick={() => {
                        floatingRef.current?.focus()
                    }}
                />
            </CSSTransition>
            <div
                className="popper-tooltip click-outside-block hotkey-block Popover Popover__box"
                tabIndex={-1} // Only programmatically focusable
                ref={setFloatingRef}
                /* eslint-disable-next-line react/forbid-dom-props */
                style={{
                    position: strategy,
                    top: y ?? 0,
                    left: x ?? 0,
                    transition: 'none',
                    zIndex: 'var(--z-definition-popover)',
                }}
                onMouseLeave={() => {
                    if (state !== DefinitionPopoverState.Edit) {
                        onMouseLeave?.()
                    }
                }}
            >
                <DefinitionPopover.Wrapper>
                    <DefinitionPopover.Header
                        title={
                            <PropertyKeyInfo
                                value={item.name ?? ''}
                                type={isElement ? 'element' : undefined}
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
            </div>
        </>
    )
}
