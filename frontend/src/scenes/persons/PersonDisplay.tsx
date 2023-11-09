import './PersonDisplay.scss'
import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture, ProfilePictureProps } from 'lib/lemon-ui/ProfilePicture'
import clsx from 'clsx'
import { Popover } from 'lib/lemon-ui/Popover'
import { PersonPreview } from './PersonPreview'
import { useMemo, useState } from 'react'
import { router } from 'kea-router'
import { asDisplay, asLink } from './person-utils'
import { useNotebookNode } from 'scenes/notebooks/Nodes/notebookNodeLogic'
import { NotebookNodeType } from '~/types'

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
}

export function PersonIcon({
    person,
    ...props
}: Pick<PersonDisplayProps, 'person'> & Omit<ProfilePictureProps, 'name' | 'email'>): JSX.Element {
    const display = asDisplay(person)

    const email: string | undefined = useMemo(() => {
        // The email property could be correct but it could also be set strangely such as an array or not even a string
        const possibleEmail = Array.isArray(person?.properties?.email)
            ? person?.properties?.email[0]
            : person?.properties?.email
        return typeof possibleEmail === 'string' ? possibleEmail : undefined
    }, [person?.properties?.email])

    return <ProfilePicture {...props} name={display} email={email} />
}

export function PersonDisplay({
    person,
    withIcon,
    noEllipsis,
    noPopover,
    noLink,
    isCentered,
    href = asLink(person),
}: PersonDisplayProps): JSX.Element {
    const display = asDisplay(person)
    const [visible, setVisible] = useState(false)

    const notebookNode = useNotebookNode()

    let content = (
        <span className={clsx('flex', 'items-center', isCentered && 'justify-center')}>
            {withIcon && <PersonIcon person={person} size={typeof withIcon === 'string' ? withIcon : 'md'} />}
            <span className={clsx('ph-no-capture', !noEllipsis && 'truncate')}>{display}</span>
        </span>
    )

    content = (
        <span
            className="PersonDisplay"
            onClick={
                !noPopover
                    ? () => {
                          if (visible && href && !noLink) {
                              router.actions.push(href)
                          } else {
                              setVisible(true)

                              if (notebookNode && person) {
                                  notebookNode.actions.updateAttributes({
                                      children: [
                                          {
                                              type: NotebookNodeType.Person,
                                              attrs: {
                                                  id: person.distinct_id || person.distinct_ids?.[0],
                                              },
                                          },
                                      ],
                                  })
                              }
                          }
                      }
                    : undefined
            }
        >
            {noLink || !href ? (
                content
            ) : (
                <Link
                    to={href}
                    onClick={(e) => {
                        if (!noPopover) {
                            e.preventDefault()
                            return
                        }
                    }}
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
                placement="right"
                fallbackPlacements={['bottom', 'top']}
                showArrow
            >
                {content}
            </Popover>
        )

    return content
}
