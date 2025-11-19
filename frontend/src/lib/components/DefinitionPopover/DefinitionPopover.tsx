import './DefinitionPopover.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonDivider, ProfilePicture, Spinner } from '@posthog/lemon-ui'

import { DefinitionPopoverState, definitionPopoverLogic } from 'lib/components/DefinitionPopover/definitionPopoverLogic'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { dayjs } from 'lib/dayjs'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { Link } from 'lib/lemon-ui/Link'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { getCoreFilterDefinition } from '~/taxonomy/helpers'
import { CoreFilterDefinition, UserBasicType } from '~/types'

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
                        {!hideEdit && isViewable && hasTaxonomyFeatures && <Link onClick={onEdit}>Edit</Link>}
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

function ImageCarousel({ images, loading }: { images: string[]; loading?: boolean }): JSX.Element {
    const [currentIndex, setCurrentIndex] = useState(0)

    const goToPrevious = (): void => {
        setCurrentIndex((prevIndex) => (prevIndex === 0 ? images.length - 1 : prevIndex - 1))
    }

    const goToNext = (): void => {
        setCurrentIndex((prevIndex) => (prevIndex === images.length - 1 ? 0 : prevIndex + 1))
    }

    if (!loading && images.length === 0) {
        // TODO upsell manual addition of images?
        return <></>
    }

    return (
        <div className="flex items-center gap-2">
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconChevronLeft />}
                onClick={goToPrevious}
                disabledReason={images.length <= 1 ? 'Only one image' : undefined}
            />
            <div className="flex-1 flex justify-center overflow-hidden">
                {loading ? (
                    <Spinner />
                ) : (
                    <img
                        key={currentIndex}
                        src={images[currentIndex]}
                        alt={`Screenshot ${currentIndex + 1} of ${images.length}`}
                        loading="lazy"
                        className="max-w-full h-auto object-contain transition-opacity duration-300 ease-in-out"
                        style={{ maxWidth: '600px' }}
                    />
                )}
            </div>
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconChevronRight />}
                onClick={goToNext}
                disabledReason={images.length <= 1 ? 'Only one image' : undefined}
            />
        </div>
    )
}

function Example({ value }: { value?: string }): JSX.Element {
    const { type, examples, examplesLoading } = useValues(definitionPopoverLogic)

    let data: CoreFilterDefinition | null = null

    if (
        // NB: also update "selectedItemHasPopover" below
        type === TaxonomicFilterGroupType.Events ||
        type === TaxonomicFilterGroupType.EventProperties ||
        type === TaxonomicFilterGroupType.EventFeatureFlags ||
        type === TaxonomicFilterGroupType.PersonProperties ||
        type === TaxonomicFilterGroupType.GroupsPrefix ||
        type === TaxonomicFilterGroupType.Metadata ||
        type === TaxonomicFilterGroupType.SessionProperties
    ) {
        data = getCoreFilterDefinition(value, type)
    } else if (type === TaxonomicFilterGroupType.Elements) {
        data = getCoreFilterDefinition(value, type)
    }

    const textExample = data?.examples?.[0] ? (
        <div className="definition-popover-examples">Example: {data?.examples?.join(', ')}</div>
    ) : (
        <></>
    )

    const imageExample = examples.length > 0 ? <ImageCarousel images={examples} loading={examplesLoading} /> : <></>

    return (
        <div className="flex flex-col gap-2">
            {textExample}
            {imageExample}
        </div>
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
                        <Owner user={updatedBy} />
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
                        <span className="definition-popover-timemeta-spacer">by</span> <Owner user={createdBy} />
                    </span>
                )}
            </div>
        )
    }
    return <></>
}

function Owner({ user }: { user?: UserBasicType | null }): JSX.Element {
    return (
        <>
            {user?.uuid ? (
                <div className="flex items-center flex-row">
                    <ProfilePicture user={user} size="sm" />
                    <span className="pl-2 inline-flex font-semibold whitespace-nowrap">{user.first_name}</span>
                </div>
            ) : (
                <span className="text-secondary italic inline-flex font-semibold pl-1 whitespace-nowrap">No owner</span>
            )}
        </>
    )
}

function HorizontalLine({ className, label }: { className?: string; label?: string }): JSX.Element {
    return (
        <LemonDivider
            className={clsx('DefinitionPopover items-start my-4', className)}
            label={label && <span className="DefinitionPopover__label">{label}</span>}
        />
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
}
