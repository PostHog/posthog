import './DefinitionPopup.scss'
import React from 'react'
import clsx from 'clsx'
import { definitionPopupLogic, DefinitionPopupState } from 'lib/components/TaxonomicFilter/definitionPopupLogic'
import { BindLogic, useActions, useValues } from 'kea'
import { TaxonomicFilterGroup, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { getKeyMapping, PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
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
import { Divider, DividerProps } from 'antd'

interface HeaderProps {
    title: React.ReactNode
    headerTitle: React.ReactNode
    icon: React.ReactNode
}

interface DefinitionPopupProps {
    children: React.ReactNode
}

// Wrapper
function DefinitionPopup({ title, icon, headerTitle, children }: DefinitionPopupProps & HeaderProps): JSX.Element {
    const { state } = useValues(definitionPopupLogic)
    return (
        <div className={clsx('definition-popup', state)}>
            <Header title={title} headerTitle={headerTitle} icon={icon} />
            {children}
        </div>
    )
}

function Header({ title, headerTitle, icon }: HeaderProps): JSX.Element {
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
                    <a onClick={() => setPopupState(DefinitionPopupState.View)}>Edit</a>
                </div>
            ) : (
                <>
                    <div className="definition-popup-header-row">
                        <div className="definition-popup-header-row-title">{headerTitle}</div>
                        <a onClick={() => setPopupState(DefinitionPopupState.Edit)}>View</a>
                    </div>
                    <div className="definition-popup-title">
                        {icon} {title}
                    </div>
                </>
            )}
        </div>
    )
}

function Description({ description }: { description: string }): JSX.Element {
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

function HorizontalLine(props: DividerProps): JSX.Element {
    return <Divider className="definition-popup-divider" {...props} />
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

function Card({ title, value }: { title: string; value: React.ReactNode }): JSX.Element {
    return (
        <div className="definition-popup-grid-card">
            <div className="definition-popup-grid-card-title">{title}</div>
            <div className="definition-popup-grid-card-content">{value}</div>
        </div>
    )
}

DefinitionPopup.Description = Description
DefinitionPopup.DescriptionEmpty = DescriptionEmpty
DefinitionPopup.Example = Example
DefinitionPopup.TimeMeta = TimeMeta
DefinitionPopup.HorizontalLine = HorizontalLine
DefinitionPopup.Grid = Grid
DefinitionPopup.Section = Section
DefinitionPopup.Card = Card

// TaxonomicFilterGroupType.Actions,
// TaxonomicFilterGroupType.Elements,
// X TaxonomicFilterGroupType.Events,
// X TaxonomicFilterGroupType.CustomEvents,
// TaxonomicFilterGroupType.EventProperties,
// TaxonomicFilterGroupType.PersonProperties,
// TaxonomicFilterGroupType.Cohorts,
// TaxonomicFilterGroupType.CohortsWithAllUsers,

const formatTimeFromNow = (day?: string): string => (day ? dayjs.utc(day).fromNow() : '-')

const renderRestOfDefinition = (
    item: EventDefinition | PropertyDefinition | CohortType | ActionType | PersonProperty,
    listGroupType: TaxonomicFilterGroupType
): JSX.Element => {
    if ([TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.CustomEvents].includes(listGroupType)) {
        const _item = item as EventDefinition
        return (
            <>
                <Grid cols={2}>
                    <Card title="First seen" value={formatTimeFromNow(_item.created_at)} />
                    <Card title="Last seen" value={formatTimeFromNow(_item.last_seen_at)} />
                    <Card title="30 day volume" value={_item.volume_30_day ?? '-'} />
                    <Card title="30 day queries" value={_item.query_usage_30_day ?? '-'} />
                </Grid>
                <HorizontalLine />
                <Section>
                    <Card
                        title="Sent as"
                        value={<span style={{ fontFamily: 'monaco', fontSize: 12 }}>{_item.name}</span>}
                    />
                </Section>
            </>
        )
    }
    if ([TaxonomicFilterGroupType.Actions].includes(listGroupType)) {
        const _item = item as ActionType
        return (
            <>
                <Grid cols={2}>
                    <Card title="First seen" value={formatTimeFromNow(_item.created_at)} />
                    {/*<Card title="Last seen" value={formatTimeFromNow(_item.last_seen_at)}/>*/}
                    {/*<Card title="30 day volume" value={_item.volume_30_day ?? '-'}/>*/}
                    {/*<Card title="30 day queries" value={_item.query_usage_30_day ?? '-'}/>*/}
                </Grid>
                <HorizontalLine />
                <Section>
                    <Card
                        title="Sent as"
                        value={<span style={{ fontFamily: 'monaco', fontSize: 12 }}>{_item.name}</span>}
                    />
                </Section>
            </>
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

    console.log('ITEM', item)

    const icon = group.getIcon?.(item)
    return (
        <BindLogic
            logic={definitionPopupLogic}
            props={{
                type: listGroupType,
            }}
        >
            <DefinitionPopup
                title={<PropertyKeyInfo value={item.name ?? ''} disablePopover disableIcon={!!icon} />}
                headerTitle={group.getPopupHeader(item)}
                icon={icon}
            >
                {'description' in item &&
                    (item.description ? (
                        <DefinitionPopup.Description description={item.description} />
                    ) : (
                        <DefinitionPopup.DescriptionEmpty />
                    ))}
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
                <HorizontalLine />
                {/* Things start to get different here */}
                {renderRestOfDefinition(item, listGroupType)}
            </DefinitionPopup>
        </BindLogic>
    )

    return item.name ?? ''
}

export { DefinitionPopup }
