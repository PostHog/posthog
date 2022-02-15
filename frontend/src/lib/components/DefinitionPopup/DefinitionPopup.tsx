import './DefinitionPopup.scss'
import React from 'react'
import clsx from 'clsx'
import { definitionPopupLogic, DefinitionPopupState } from 'lib/components/DefinitionPopup/definitionPopupLogic'
import { BindLogic, useActions, useValues } from 'kea'
import { SimpleOption, TaxonomicFilterGroup, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { getKeyMapping, keyMapping, PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import {
    ActionType,
    CohortType,
    EventDefinition,
    KeyMapping,
    PersonProperty,
    PropertyDefinition,
    UserBasicType,
} from '~/types'
import { Owner } from 'scenes/events/Owner'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils'
import { ObjectTags } from 'lib/components/ObjectTags'
import { Divider, DividerProps, Typography } from 'antd'
import { ActionPopupInfo } from 'lib/components/DefinitionPopup/ActionPopupInfo'
import { CohortPopupInfo } from 'lib/components/DefinitionPopup/CohortPopupInfo'
import { LockOutlined } from '@ant-design/icons'
import { Link } from 'lib/components/Link'
import { IconOpenInNew } from 'lib/components/icons'

interface HeaderProps {
    title: React.ReactNode
    headerTitle: React.ReactNode
    icon: React.ReactNode
    editText?: string
    viewText?: string
}

interface DefinitionPopupProps {
    children: React.ReactNode
}

// Wrapper
function DefinitionPopup({
    title,
    icon,
    headerTitle,
    children,
    editText,
    viewText,
}: DefinitionPopupProps & HeaderProps): JSX.Element {
    const { state } = useValues(definitionPopupLogic)
    return (
        <div className={clsx('definition-popup', state)}>
            <Header title={title} headerTitle={headerTitle} icon={icon} editText={editText} viewText={viewText} />
            {children}
        </div>
    )
}

function Header({ title, headerTitle, icon, editText = 'Edit', viewText = 'View' }: HeaderProps): JSX.Element {
    const { state } = useValues(definitionPopupLogic)
    const { setPopupState } = useActions(definitionPopupLogic)
    const isEdit = state === DefinitionPopupState.Edit

    return (
        <div className="definition-popup-header">
            {isEdit ? (
                <div className="definition-popup-header-row">
                    <div className="definition-popup-title">
                        {icon} {title}
                    </div>
                    <div className="definition-popup-header-row-buttons">
                        <a onClick={() => setPopupState(DefinitionPopupState.View)}>{editText}</a>
                    </div>
                </div>
            ) : (
                <>
                    <div className="definition-popup-header-row">
                        <div className="definition-popup-header-row-title">{headerTitle}</div>
                        <div className="definition-popup-header-row-buttons" style={{ display: 'blank' /* TODO */ }}>
                            <a onClick={() => setPopupState(DefinitionPopupState.Edit)}>{viewText}</a>
                        </div>
                    </div>
                    <div className="definition-popup-title">
                        {icon} {title}
                    </div>
                </>
            )}
        </div>
    )
}

function Description({ description }: { description: React.ReactNode }): JSX.Element {
    return <div className="definition-popup-description">{description}</div>
}

function DescriptionEmpty(): JSX.Element {
    const { type } = useValues(definitionPopupLogic)
    return (
        <div className="definition-popup-description empty">
            There is no description for this {getSingularType(type)}
        </div>
    )
}

export function getSingularType(type: TaxonomicFilterGroupType): string {
    switch (type) {
        case TaxonomicFilterGroupType.Actions:
            return 'action'
        case TaxonomicFilterGroupType.Cohorts:
        case TaxonomicFilterGroupType.CohortsWithAllUsers:
            return 'cohort'
        case TaxonomicFilterGroupType.Elements:
            return 'element'
        case TaxonomicFilterGroupType.Events:
        case TaxonomicFilterGroupType.CustomEvents:
            return 'event'
        case TaxonomicFilterGroupType.EventProperties:
        case TaxonomicFilterGroupType.PersonProperties:
        case TaxonomicFilterGroupType.GroupsPrefix: // Group properties
            return 'property'
        case TaxonomicFilterGroupType.PageviewUrls:
            return 'pageview url'
        case TaxonomicFilterGroupType.Screens:
            return 'screen'
        case TaxonomicFilterGroupType.Wildcards:
            return 'wildcard'
        default:
            return 'definition'
    }
}

function Example({ value }: { value: string }): JSX.Element {
    const { type } = useValues(definitionPopupLogic)
    let data: KeyMapping | null = null

    if (
        // NB: also update "selectedItemHasPopup" below
        type === TaxonomicFilterGroupType.Events ||
        type === TaxonomicFilterGroupType.EventProperties ||
        type === TaxonomicFilterGroupType.PersonProperties ||
        type === TaxonomicFilterGroupType.GroupsPrefix
    ) {
        data = getKeyMapping(value, 'event')
    } else if (type === TaxonomicFilterGroupType.Elements) {
        data = getKeyMapping(value, 'element')
    }

    return data?.examples?.[0] ? (
        <div className="definition-popup-examples">Example: {data?.examples?.join(', ')}</div>
    ) : (
        <></>
    )
}

function TimeMeta({
    createdAt,
    createdBy,
    updatedAt,
    updatedBy,
}: {
    createdAt?: string
    createdBy?: UserBasicType
    updatedAt?: string
    updatedBy?: UserBasicType
}): JSX.Element {
    // If updatedAt doesn't exist, fallback on showing creator
    if (updatedAt) {
        const secondsAgo = dayjs.duration(dayjs().diff(dayjs.utc(updatedAt))).asSeconds()
        return (
            <div className="definition-popup-timemeta">
                Last modified {secondsAgo < 5 ? 'a few seconds' : humanFriendlyDuration(secondsAgo, 1)} ago{' '}
                {updatedBy && (
                    <>
                        <span className="definition-popup-timemeta-spacer">by</span>{' '}
                        <Owner user={updatedBy} style={{ fontWeight: 600, paddingLeft: 4 }} />
                    </>
                )}
            </div>
        )
    }
    if (createdAt) {
        const secondsAgo = dayjs.duration(dayjs().diff(dayjs.utc(createdAt))).asSeconds()
        return (
            <div className="definition-popup-timemeta">
                Created {secondsAgo < 5 ? 'a few seconds' : humanFriendlyDuration(secondsAgo, 1)} ago{' '}
                {updatedBy && (
                    <>
                        <span className="definition-popup-timemeta-spacer">by</span>{' '}
                        <Owner user={createdBy} style={{ fontWeight: 600, paddingLeft: 4 }} />
                    </>
                )}
            </div>
        )
    }
    return <></>
}

function HorizontalLine({ children, ...props }: DividerProps): JSX.Element {
    return (
        <Divider className="definition-popup-divider" {...props}>
            {children}
        </Divider>
    )
}

interface GridProps {
    children: React.ReactNode
    cols?: number
}

function Grid({ children, cols }: GridProps): JSX.Element {
    return (
        <div className="definition-popup-grid" style={{ gridTemplateColumns: `repeat(${cols}, auto)` }}>
            {children}
        </div>
    )
}

function Section({ children }: GridProps): JSX.Element {
    return <Grid cols={1}>{children}</Grid>
}

function Card({
    title,
    value,
    alignItems = 'baseline',
}: {
    title: string | JSX.Element
    value: React.ReactNode
    alignItems?: 'baseline' | 'center' | 'end'
}): JSX.Element {
    return (
        <div className="definition-popup-grid-card" style={{ alignItems }}>
            <div className="definition-popup-grid-card-title">{title}</div>
            <div className="definition-popup-grid-card-content">{value}</div>
        </div>
    )
}

function Type({ propertyType }: { propertyType: PropertyDefinition['property_type'] | null }): JSX.Element {
    return propertyType ? (
        <div className="definition-popup-grid-card">
            <div className="property-value-type">{propertyType}</div>
        </div>
    ) : (
        <></>
    )
}

function Footer({
    name,
    propertyType,
}: {
    name: string | null | undefined
    propertyType: PropertyDefinition['property_type'] | null
}): JSX.Element {
    return (
        <Grid cols={2}>
            <Card
                title="Sent as"
                value={
                    <>
                        <Typography.Text
                            ellipsis={true}
                            title={name ?? undefined} // because Text can cope with undefined but not null ¯\_(ツ)_/¯
                            style={{ fontFamily: 'monaco', fontSize: 12, maxWidth: '20em' }}
                        >
                            {name !== '' ? name : <i>(empty string)</i>}
                        </Typography.Text>
                    </>
                }
            />
            <Card title={<>&nbsp;</>} value={<DefinitionPopup.Type propertyType={propertyType} />} alignItems={'end'} />
        </Grid>
    )
}

DefinitionPopup.Description = Description
DefinitionPopup.DescriptionEmpty = DescriptionEmpty
DefinitionPopup.Example = Example
DefinitionPopup.Type = Type
DefinitionPopup.TimeMeta = TimeMeta
DefinitionPopup.HorizontalLine = HorizontalLine
DefinitionPopup.Grid = Grid
DefinitionPopup.Section = Section
DefinitionPopup.Card = Card
DefinitionPopup.Footer = Footer

const formatTimeFromNow = (day?: string): string => (day ? dayjs.utc(day).fromNow() : '-')

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
            <LockOutlined style={{ marginRight: 6, color: 'var(--warning)' }} />
        </div>
    )

    return (
        <>
            <Grid cols={2}>
                <Card title="First seen" value={<Lock />} />
                <Card title="Last seen" value={<Lock />} />
                <Card title="30 day volume" value={<Lock />} />
                <Card title="30 day queries" value={<Lock />} />
            </Grid>
            <Section>
                <Link
                    to="https://posthog.com/docs/user-guides"
                    target="_blank"
                    data-attr="taxonomy-learn-more"
                    style={{ fontWeight: 600, marginTop: 8 }}
                >
                    Learn more about Taxonomy
                    <IconOpenInNew style={{ marginLeft: 8 }} />
                </Link>
            </Section>
        </>
    )
}

const renderRestOfDefinition = (
    item: EventDefinition | PropertyDefinition | CohortType | ActionType | PersonProperty,
    listGroupType: TaxonomicFilterGroupType,
    hasTaxonomyFeatures: boolean = false
): JSX.Element => {
    if ([TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.CustomEvents].includes(listGroupType)) {
        const _item = item as EventDefinition
        return (
            <>
                {hasTaxonomyFeatures ? (
                    <Grid cols={2}>
                        <Card title="First seen" value={formatTimeFromNow(_item.created_at)} />
                        <Card title="Last seen" value={formatTimeFromNow(_item.last_seen_at)} />
                        <Card title="30 day volume" value={_item.volume_30_day ?? '-'} />
                        <Card title="30 day queries" value={_item.query_usage_30_day ?? '-'} />
                    </Grid>
                ) : (
                    <TaxonomyIntroductionSection />
                )}
                <HorizontalLine />
                <DefinitionPopup.Footer name={item.name} propertyType={(item as PropertyDefinition)?.property_type} />
            </>
        )
    }
    if ([TaxonomicFilterGroupType.Actions].includes(listGroupType)) {
        const _item = item as ActionType
        return (
            <>
                <ActionPopupInfo entity={_item} />
                {(_item?.steps?.length || 0) > 0 && <HorizontalLine />}
                <Grid cols={2}>
                    <Card title="First seen" value={formatTimeFromNow(_item.created_at)} />
                </Grid>
            </>
        )
    }
    if (
        [TaxonomicFilterGroupType.EventProperties, TaxonomicFilterGroupType.PersonProperties].includes(listGroupType) ||
        listGroupType.startsWith(TaxonomicFilterGroupType.GroupsPrefix)
    ) {
        const _item = item as PropertyDefinition
        return (
            <>
                <Grid cols={2}>
                    <Card title="First seen" value={formatTimeFromNow(_item.created_at)} />
                    <Card title="Last seen" value={formatTimeFromNow(_item.last_seen_at)} />
                    <Card title="30 day volume" value={_item.volume_30_day ?? '-'} />
                    <Card title="30 day queries" value={_item.query_usage_30_day ?? '-'} />
                </Grid>
                <HorizontalLine />
                <DefinitionPopup.Footer name={_item.name} propertyType={_item.property_type} />
            </>
        )
    }
    if ([TaxonomicFilterGroupType.Cohorts, TaxonomicFilterGroupType.CohortsWithAllUsers].includes(listGroupType)) {
        const _item = item as CohortType
        if (listGroupType === TaxonomicFilterGroupType.CohortsWithAllUsers) {
            return (
                <Grid cols={2}>
                    <Card title="Persons" value={_item.count ?? 0} />
                    <Card title="Last calculated" value={formatTimeFromNow(_item.last_calculation)} />
                </Grid>
            )
        }
        if (!_item.is_static) {
            return (
                <>
                    <Grid cols={2}>
                        <Card title="Persons" value={_item.count ?? 0} />
                        <Card title="Last calculated" value={formatTimeFromNow(_item.last_calculation)} />
                    </Grid>
                    {(_item.groups?.length || 0 > 0) && <HorizontalLine />}
                    <CohortPopupInfo entity={_item} />
                </>
            )
        }
        return (
            <Grid cols={2}>
                <Card title="Persons" value={_item.count ?? 0} />
                <Card title="Last calculated" value={formatTimeFromNow(_item.last_calculation)} />
            </Grid>
        )
    }
    if ([TaxonomicFilterGroupType.Elements].includes(listGroupType)) {
        const _item = item as SimpleOption
        return (
            <Section>
                <Card
                    title="Sent as"
                    value={<span style={{ fontFamily: 'monaco', fontSize: 12 }}>{_item.name}</span>}
                />
            </Section>
        )
    }
    return <></>
}

export const renderItemPopup = (
    item: EventDefinition | PropertyDefinition | CohortType | ActionType | PersonProperty,
    listGroupType: TaxonomicFilterGroupType,
    group: TaxonomicFilterGroup,
    hasTaxonomyFeatures: boolean
): React.ReactNode => {
    // Supports all types specified in selectedItemHasPopup
    const value = group.getValue(item)

    if (!value) {
        return
    }

    const icon = group.getIcon?.(item)
    return (
        <BindLogic
            logic={definitionPopupLogic}
            props={{
                type: listGroupType,
            }}
        >
            <DefinitionPopup
                title={
                    <PropertyKeyInfo
                        value={item.name ?? ''}
                        type={listGroupType === TaxonomicFilterGroupType.Elements ? 'element' : undefined}
                        disablePopover
                        disableIcon={!!icon}
                    />
                }
                headerTitle={group.getPopupHeader(item)}
                icon={icon}
                editText={listGroupType === TaxonomicFilterGroupType.Actions ? 'Quick edit' : undefined}
            >
                {hasTaxonomyFeatures &&
                    'description' in item &&
                    (hasTaxonomyFeatures && item.description ? (
                        <DefinitionPopup.Description description={item.description} />
                    ) : (
                        <DefinitionPopup.DescriptionEmpty />
                    ))}
                {listGroupType === TaxonomicFilterGroupType.Elements && item.name && (
                    <DefinitionPopup.Description description={keyMapping.element[item.name].description} />
                )}
                <DefinitionPopup.Example value={value.toString()} />
                {hasTaxonomyFeatures && 'tags' in item && !!item.tags?.length && (
                    <ObjectTags tags={item.tags} style={{ marginBottom: 4 }} />
                )}
                <DefinitionPopup.TimeMeta
                    createdAt={('created_at' in item && item.created_at) || undefined}
                    createdBy={('created_by' in item && item.created_by) || undefined}
                    updatedAt={('updated_at' in item && item.updated_at) || undefined}
                    updatedBy={('updated_by' in item && item.updated_by) || undefined}
                />
                <DefinitionPopup.HorizontalLine />
                {/* Things start to get different here */}
                {renderRestOfDefinition(item, listGroupType, hasTaxonomyFeatures)}
            </DefinitionPopup>
        </BindLogic>
    )

    return item.name ?? ''
}

export { DefinitionPopup }
