import './PersonDisplay.scss'

import clsx from 'clsx'
import { router } from 'kea-router'
import { Link } from 'lib/lemon-ui/Link'
import { Popover } from 'lib/lemon-ui/Popover'
import { ProfilePicture, ProfilePictureProps } from 'lib/lemon-ui/ProfilePicture'
import { useMemo, useState } from 'react'
import { useNotebookNode } from 'scenes/notebooks/Nodes/NotebookNodeContext'

import { asDisplay, asLink } from './person-utils'
import { PersonPreview } from './PersonPreview'

type PersonPropType =
    | { properties?: Record<string, any>; distinct_ids?: string[]; distinct_id?: never }
    | { properties?: Record<string, any>; distinct_ids?: never; distinct_id?: string }

export interface PersonDisplayProps {
    person?: PersonPropType | null
    withIcon?: boolean | ProfilePictureProps['size']
    href?: string
    noLink?: boolean
    noEllipsis?: boolean
    noPopover?: boolean
    isCentered?: boolean
    children?: React.ReactNode
}

export function PersonIcon({
    person,
    ...props
}: Pick<PersonDisplayProps, 'person'> & Omit<ProfilePictureProps, 'user' | 'name' | 'email'>): JSX.Element {
    const display = asDisplay(person)

    const email: string | undefined = useMemo(() => {
        // The email property could be correct but it could also be set strangely such as an array or not even a string
        const possibleEmail = Array.isArray(person?.properties?.email)
            ? person?.properties?.email[0]
            : person?.properties?.email
        return typeof possibleEmail === 'string' ? possibleEmail : undefined
    }, [person?.properties?.email])

    return (
        <ProfilePicture
            {...props}
            user={{
                first_name: display,
                email,
            }}
        />
    )
}

export function PersonDisplay({
    person,
    withIcon,
    noEllipsis,
    noPopover,
    noLink,
    isCentered,
    href = asLink(person),
    children,
}: PersonDisplayProps): JSX.Element {
    const display = asDisplay(person)
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
        <span className={clsx('flex items-center', isCentered && 'justify-center')}>
            {withIcon && <PersonIcon person={person} size={typeof withIcon === 'string' ? withIcon : 'md'} />}
            <span className={clsx('ph-no-capture', !noEllipsis && 'truncate')}>{display}</span>
        </span>
    )

    content = (
        <span className="PersonDisplay" onClick={!noPopover ? handleClick : undefined}>
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

    content =
        noPopover || notebookNode ? (
            content
        ) : (
            <Popover
                overlay={
                    <PersonPreview
                        distinctId={person?.distinct_id || person?.distinct_ids?.[0]}
                        onClose={() => setVisible(false)}
                    />
                }
                visible={visible}
                onClickOutside={() => setVisible(false)}
                placement="top"
                fallbackPlacements={['bottom', 'right']}
                showArrow
            >
                {content}
            </Popover>
        )

    return content
}
