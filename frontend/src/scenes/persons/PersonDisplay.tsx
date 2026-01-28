import './PersonDisplay.scss'

import clsx from 'clsx'
import { router } from 'kea-router'
import React, { useMemo, useState } from 'react'

import { IconCopy } from '@posthog/icons'

import { Link } from 'lib/lemon-ui/Link'
import { Popover } from 'lib/lemon-ui/Popover'
import { ProfilePicture, ProfilePictureProps } from 'lib/lemon-ui/ProfilePicture'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { useNotebookNode } from 'scenes/notebooks/Nodes/NotebookNodeContext'

import { PersonPreview } from './PersonPreview'
import { PersonPropType, asDisplay, asLink, getPersonColorIndex } from './person-utils'

export interface PersonDisplayProps {
    person?: PersonPropType | null
    displayName?: string
    withIcon?: boolean | ProfilePictureProps['size']
    href?: string
    noLink?: boolean
    noEllipsis?: boolean
    noPopover?: boolean
    isCentered?: boolean
    children?: React.ReactChild
    withCopyButton?: boolean
    placement?: 'top' | 'bottom' | 'left' | 'right'
    inline?: boolean
    className?: string
    /** Use muted/secondary text color instead of default */
    muted?: boolean
}

export function PersonIcon({
    person,
    displayName,
    index,
    ...props
}: Pick<PersonDisplayProps, 'person'> &
    Omit<ProfilePictureProps, 'user' | 'name' | 'email'> & { displayName?: string }): JSX.Element {
    const display = displayName || asDisplay(person)

    const email: string | undefined = useMemo(() => {
        // The email property could be correct but it could also be set strangely such as an array or not even a string
        const possibleEmail = Array.isArray(person?.properties?.email)
            ? person?.properties?.email[0]
            : person?.properties?.email
        return typeof possibleEmail === 'string' ? possibleEmail : undefined
    }, [person?.properties?.email])

    // Generate a stable color index from the person's distinct_id if not explicitly provided
    //
    // Don't depend on `person` for the memoization since this is only used to get an accurate color
    // and person is a complex object that could change.
    // oxlint-disable-next-line react-hooks/exhaustive-deps
    const colorIndex = useMemo(() => index ?? getPersonColorIndex(person), [index])

    return (
        <ProfilePicture
            {...props}
            index={colorIndex}
            user={{
                first_name: display,
                email,
            }}
        />
    )
}

export function PersonDisplay({
    person,
    displayName,
    withIcon,
    noEllipsis,
    noPopover,
    noLink,
    isCentered,
    href = asLink(person),
    children,
    withCopyButton,
    placement,
    inline,
    className,
    muted,
}: PersonDisplayProps): JSX.Element {
    const display = displayName || asDisplay(person)
    const [visible, setVisible] = useState(false)

    const notebookNode = useNotebookNode()

    const handleClick = (e: React.MouseEvent): void => {
        if (visible && href && !noLink && person?.properties) {
            router.actions.push(href)
        } else if (visible && !person?.properties) {
            e.preventDefault()
        } else {
            setVisible(true)
        }
        return
    }

    let content = children || (
        <span className={clsx(!inline && 'flex items-center', isCentered && 'justify-center')}>
            {withIcon && (
                <PersonIcon
                    displayName={displayName}
                    person={person}
                    size={typeof withIcon === 'string' ? withIcon : 'md'}
                />
            )}
            <span className={clsx('ph-no-capture', !noEllipsis && 'truncate')}>{display}</span>
        </span>
    )

    content = (
        <span
            className={clsx('PersonDisplay', muted && 'PersonDisplay--muted', className)}
            onClick={!noPopover ? handleClick : undefined}
        >
            {noLink || !href || (visible && !person?.properties) ? (
                content
            ) : (
                <Link
                    to={href}
                    onClick={(e: React.MouseEvent): void => {
                        if (!noPopover && !notebookNode) {
                            e.preventDefault()
                            return
                        }
                    }}
                    subtle
                    data-attr={`goto-person-email-${person?.distinct_id || person?.distinct_ids?.[0]}`}
                >
                    {content}
                </Link>
            )}
        </span>
    )

    if (noPopover || notebookNode) {
        return content
    }

    return (
        <Popover
            overlay={
                person?.distinct_id || person?.distinct_ids?.[0] || person?.id ? (
                    <PersonPreview
                        distinctId={person?.distinct_id || person?.distinct_ids?.[0]}
                        personId={person?.id}
                        onClose={() => setVisible(false)}
                    />
                ) : null
            }
            visible={visible}
            onClickOutside={() => setVisible(false)}
            placement={placement || 'top'}
            fallbackPlacements={['bottom', 'right']}
            showArrow
        >
            {withCopyButton ? (
                <div className="flex flex-row items-center justify-between gap-2 min-w-0">
                    <span className="min-w-0 flex-1">{content}</span>
                    <IconCopy
                        className="text-lg cursor-pointer shrink-0"
                        onClick={() => void copyToClipboard(display)}
                    />
                </div>
            ) : (
                <span>{content}</span>
            )}
        </Popover>
    )
}
