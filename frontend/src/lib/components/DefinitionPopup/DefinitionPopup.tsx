import './DefinitionPopup.scss'
import React from 'react'
import clsx from 'clsx'
import { definitionPopupLogic, DefinitionPopupState } from 'lib/components/DefinitionPopup/definitionPopupLogic'
import { useActions, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { getKeyMapping } from 'lib/components/PropertyKeyInfo'
import { KeyMapping, UserBasicType } from '~/types'
import { Owner } from 'scenes/events/Owner'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils'
import { Divider, DividerProps, Select } from 'antd'
import { membersLogic } from 'scenes/organization/Settings/membersLogic'
import { Link } from 'lib/components/Link'

interface DefinitionPopupProps {
    children: React.ReactNode
}

// Wrapper
function Wrapper({ children }: DefinitionPopupProps): JSX.Element {
    const { state } = useValues(definitionPopupLogic)
    return <div className={clsx('definition-popup', state)}>{children}</div>
}

interface HeaderProps {
    title: React.ReactNode
    headerTitle: React.ReactNode
    editHeaderTitle: React.ReactNode
    icon: React.ReactNode
    hideEdit?: boolean
    hideView?: boolean
    onEdit?: () => void
    onView?: () => void
}

function Header({
    title,
    headerTitle,
    editHeaderTitle,
    icon,
    hideEdit = false,
    hideView = false,
    onEdit: _onEdit,
    onView: _onView,
}: HeaderProps): JSX.Element {
    const { state, viewFullDetailUrl } = useValues(definitionPopupLogic)
    const { setPopupState } = useActions(definitionPopupLogic)
    const onEdit = (): void => {
        setPopupState(DefinitionPopupState.Edit)
        _onEdit?.()
    }
    const onView = (): void => {
        setPopupState(DefinitionPopupState.View)
        _onView?.()
    }

    return (
        <div className="definition-popup-header">
            <div className="definition-popup-header-row">
                <div className="definition-popup-header-row-title">
                    {state === DefinitionPopupState.Edit ? editHeaderTitle : headerTitle}
                </div>
                {state === DefinitionPopupState.View && (
                    <div className="definition-popup-header-row-buttons click-outside-block">
                        {!hideEdit && <a onClick={onEdit}>Edit</a>}
                        {!hideView && (
                            <Link target="_blank" to={viewFullDetailUrl} onClick={onView}>
                                View
                            </Link>
                        )}
                    </div>
                )}
            </div>
            <div className="definition-popup-title">
                {icon} {title}
            </div>
        </div>
    )
}

function Description({ description }: { description: React.ReactNode }): JSX.Element {
    return <div className="definition-popup-description">{description}</div>
}

function DescriptionEmpty(): JSX.Element {
    const { singularType } = useValues(definitionPopupLogic)
    return <div className="definition-popup-description empty">There is no description for this {singularType}</div>
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

function Card({ title, value }: { title: string; value: React.ReactNode }): JSX.Element {
    return (
        <div className="definition-popup-grid-card">
            <div className="definition-popup-grid-card-title">{title}</div>
            <div className="definition-popup-grid-card-content">{value}</div>
        </div>
    )
}

function OwnerDropdown(): JSX.Element {
    const { members } = useValues(membersLogic)
    const { localDefinition } = useValues(definitionPopupLogic)
    const { setLocalDefinition } = useActions(definitionPopupLogic)

    return (
        <Select
            className={'definition-popup-owner-select definition-popup-edit-form-value'}
            placeholder={<Owner user={'owner' in localDefinition ? localDefinition?.owner : null} />}
            style={{ minWidth: 200 }}
            dropdownClassName="owner-option"
            onChange={(val) => {
                const newOwner = members.find((mem) => mem.user.id === val)?.user
                if (newOwner) {
                    setLocalDefinition({ owner: newOwner })
                } else {
                    setLocalDefinition({ owner: null })
                }
            }}
        >
            <Select.Option key="no-owner" value={-1}>
                <Owner user={null} />
            </Select.Option>
            {members.map((member) => (
                <Select.Option key={member.user.id} value={member.user.id}>
                    <Owner user={member.user} />
                </Select.Option>
            ))}
        </Select>
    )
}

export const DefinitionPopup = {
    Wrapper,
    Header,
    Description,
    DescriptionEmpty,
    Example,
    TimeMeta,
    HorizontalLine,
    Grid,
    Section,
    Card,
    OwnerDropdown,
}
