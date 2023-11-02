import './DefinitionPopover.scss'
import clsx from 'clsx'
import { definitionPopoverLogic, DefinitionPopoverState } from 'lib/components/DefinitionPopover/definitionPopoverLogic'
import { useActions, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { getKeyMapping } from 'lib/taxonomy'
import { KeyMapping, UserBasicType, PropertyDefinition } from '~/types'
import { Owner } from 'scenes/events/Owner'
import { dayjs } from 'lib/dayjs'
import { Divider, DividerProps, Select } from 'antd'
import { membersLogic } from 'scenes/organization/Settings/membersLogic'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

interface DefinitionPopoverProps {
    children: React.ReactNode
}

// Wrapper
function Wrapper({ children }: DefinitionPopoverProps): JSX.Element {
    const { state } = useValues(definitionPopoverLogic)
    return <div className={clsx('definition-popover', state)}>{children}</div>
}

interface HeaderProps {
    title: React.ReactNode
    headerTitle: React.ReactNode
    editHeaderTitle: React.ReactNode
    icon: React.ReactNode
    onEdit?: () => void
    onView?: () => void
}

function Header({
    title,
    headerTitle,
    editHeaderTitle,
    icon,
    onEdit: _onEdit,
    onView: _onView,
}: HeaderProps): JSX.Element {
    const { state, type, viewFullDetailUrl, hasTaxonomyFeatures, hideView, hideEdit, isViewable, openDetailInNewTab } =
        useValues(definitionPopoverLogic)
    const { setPopoverState } = useActions(definitionPopoverLogic)
    const { reportDataManagementDefinitionClickView, reportDataManagementDefinitionClickEdit } =
        useActions(eventUsageLogic)
    const onEdit = (): void => {
        if (hasTaxonomyFeatures) {
            setPopoverState(DefinitionPopoverState.Edit)
            _onEdit?.()
            reportDataManagementDefinitionClickEdit(type)
        }
    }
    const onView = (): void => {
        setPopoverState(DefinitionPopoverState.View)
        _onView?.()
        reportDataManagementDefinitionClickView(type)
    }

    return (
        <div className="definition-popover-header">
            <div className="definition-popover-header-row">
                <div className="definition-popover-header-row-title">
                    {state === DefinitionPopoverState.Edit ? editHeaderTitle : headerTitle}
                </div>
                {state === DefinitionPopoverState.View && (
                    <div className="definition-popover-header-row-buttons click-outside-block">
                        {!hideEdit &&
                            isViewable &&
                            (hasTaxonomyFeatures ? (
                                <Link onClick={onEdit}>Edit</Link>
                            ) : (
                                <Tooltip title="Creating and editing definitions require a premium license">
                                    <Link onClick={onEdit} className="definition-popover-disabled-button">
                                        Edit
                                    </Link>
                                </Tooltip>
                            ))}
                        {!hideView && isViewable && (
                            <Link
                                target={openDetailInNewTab ? '_blank' : undefined}
                                to={viewFullDetailUrl}
                                onClick={onView}
                            >
                                View
                            </Link>
                        )}
                    </div>
                )}
            </div>
            <div className="definition-popover-title">
                {icon}
                {title}
            </div>
        </div>
    )
}

function Description({ description }: { description: React.ReactNode }): JSX.Element {
    return typeof description === 'string' ? (
        <LemonMarkdown className="definition-popover-description" lowKeyHeadings>
            {description}
        </LemonMarkdown>
    ) : (
        <div className="definition-popover-description">{description}</div>
    )
}

function DescriptionEmpty(): JSX.Element {
    const { singularType } = useValues(definitionPopoverLogic)
    return <div className="definition-popover-description empty">Add a description for this {singularType}</div>
}

function Example({ value }: { value?: string }): JSX.Element {
    const { type } = useValues(definitionPopoverLogic)
    let data: KeyMapping | null = null

    if (
        // NB: also update "selectedItemHasPopover" below
        type === TaxonomicFilterGroupType.Events ||
        type === TaxonomicFilterGroupType.EventProperties ||
        type === TaxonomicFilterGroupType.EventFeatureFlags ||
        type === TaxonomicFilterGroupType.PersonProperties ||
        type === TaxonomicFilterGroupType.GroupsPrefix
    ) {
        data = getKeyMapping(value, 'event')
    } else if (type === TaxonomicFilterGroupType.Elements) {
        data = getKeyMapping(value, 'element')
    }

    return data?.examples?.[0] ? (
        <div className="definition-popover-examples">Example: {data?.examples?.join(', ')}</div>
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
        return (
            <span className="definition-popover-timemeta">
                <span className="definition-popover-timemeta-time">
                    Last modified {dayjs().to(dayjs.utc(updatedAt))}{' '}
                </span>
                {updatedBy && (
                    <span className="definition-popover-timemeta-user">
                        <span className="definition-popover-timemeta-spacer">by</span>
                        <Owner
                            user={updatedBy}
                            style={{ display: 'inline-flex', fontWeight: 600, paddingLeft: 4, whiteSpace: 'nowrap' }}
                        />
                    </span>
                )}
            </span>
        )
    }
    if (createdAt) {
        return (
            <div className="definition-popover-timemeta">
                <span className="definition-popover-timemeta-time">Created {dayjs().to(dayjs.utc(createdAt))} </span>
                {updatedBy && (
                    <span className="definition-popover-timemeta-user">
                        <span className="definition-popover-timemeta-spacer">by</span>{' '}
                        <Owner
                            user={createdBy}
                            style={{ display: 'inline-flex', fontWeight: 600, paddingLeft: 4, whiteSpace: 'nowrap' }}
                        />
                    </span>
                )}
            </div>
        )
    }
    return <></>
}

function HorizontalLine({ children, ...props }: DividerProps): JSX.Element {
    return (
        <Divider className="definition-popover-divider" {...props}>
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
        <div
            className="definition-popover-grid"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ gridTemplateColumns: `repeat(${cols}, auto)` }}
        >
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
    value: React.ReactNode | null
    alignItems?: 'baseline' | 'center' | 'end'
}): JSX.Element {
    return (
        <div
            className="definition-popover-grid-card"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ alignItems }}
        >
            <div className="definition-popover-grid-card-title">{title}</div>
            {value && <div className="definition-popover-grid-card-content">{value}</div>}
        </div>
    )
}

function Type({ propertyType }: { propertyType: PropertyDefinition['property_type'] | null }): JSX.Element {
    return propertyType ? (
        <div className="definition-popover-grid-card">
            <div className="property-value-type">{propertyType}</div>
        </div>
    ) : (
        <></>
    )
}

function OwnerDropdown(): JSX.Element {
    const { members } = useValues(membersLogic)
    const { localDefinition } = useValues(definitionPopoverLogic)
    const { setLocalDefinition } = useActions(definitionPopoverLogic)

    return (
        <Select
            className={'definition-popover-owner-select definition-popover-edit-form-value'}
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

export const DefinitionPopover = {
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
    Type,
}
