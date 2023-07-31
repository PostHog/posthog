import './PersonHeader.scss'
import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture, ProfilePictureProps } from 'lib/lemon-ui/ProfilePicture'
import clsx from 'clsx'
import { Popover } from 'lib/lemon-ui/Popover'
import { PersonPreview } from './PersonPreview'
import { useState } from 'react'
import { router } from 'kea-router'
import { asDisplay, asLink } from './person-utils'

type PersonPropType =
    | { properties?: Record<string, any>; distinct_ids?: string[]; distinct_id?: never }
    | { properties?: Record<string, any>; distinct_ids?: never; distinct_id?: string }

export interface PersonHeaderProps {
    person?: PersonPropType | null
    withIcon?: boolean | ProfilePictureProps['size']
    noLink?: boolean
    noEllipsis?: boolean
    noPopover?: boolean
}

export function PersonHeader({ person, withIcon, noEllipsis, noPopover, noLink }: PersonHeaderProps): JSX.Element {
    const href = asLink(person)
    const display = asDisplay(person)
    const [visible, setVisible] = useState(false)

    let content = (
        <div className="flex items-center">
            {withIcon && (
                <ProfilePicture
                    name={display}
                    email={person?.properties?.email}
                    size={typeof withIcon === 'string' ? withIcon : 'md'}
                />
            )}
            <span className={clsx('ph-no-capture', !noEllipsis && 'text-ellipsis')}>{display}</span>
        </div>
    )

    content = (
        <div
            className="person-header"
            onClick={
                !noPopover
                    ? () => {
                          if (visible && href) {
                              router.actions.push(href)
                          } else {
                              setVisible(true)
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
        </div>
    )

    content = noPopover ? (
        content
    ) : (
        <Popover
            overlay={<PersonPreview distinctId={person?.distinct_id || person?.distinct_ids?.[0]} />}
            visible={visible}
            onClickOutside={() => setVisible(false)}
            placement="right"
            fallbackPlacements={['bottom', 'top']}
        >
            {content}
        </Popover>
    )

    return content
}
