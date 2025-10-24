import './ProfilePicture.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import md5 from 'md5'
import React, { useEffect, useMemo, useState } from 'react'

import { HedgehogBuddyProfile } from 'lib/components/HedgehogBuddy/HedgehogBuddyRender'
import { fullName, inStorybookTestRunner } from 'lib/utils'
import { userLogic } from 'scenes/userLogic'

import { MinimalHedgehogConfig, UserBasicType } from '~/types'

import { Lettermark, LettermarkColor } from '../Lettermark/Lettermark'
import { IconRobot } from '../icons'

export interface ProfilePictureProps {
    user?:
        | (Pick<Partial<UserBasicType>, 'first_name' | 'email' | 'last_name'> & {
              hedgehog_config?: Partial<MinimalHedgehogConfig>
          })
        | null
    name?: string
    size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl' | 'xxl'
    showName?: boolean
    className?: string
    title?: string
    index?: number
    type?: 'person' | 'bot' | 'system'
    /** Optional prop to control when gravatar loading starts. If not provided, loading is deferred automatically. */
    loading?: boolean
}

export const ProfilePicture = React.forwardRef<HTMLSpanElement, ProfilePictureProps>(function ProfilePicture(
    { user, name, size = 'lg', showName, className, index, title, type = 'person', loading },
    ref
) {
    const { user: currentUser } = useValues(userLogic)
    const [shouldLoadGravatarInternal, setShouldLoadGravatarInternal] = useState(false)
    const [gravatarLoaded, setGravatarLoaded] = useState<boolean | undefined>()

    let email = user?.email

    if (user) {
        name = fullName(user)
        email = user.email
    }

    const combinedNameAndEmail = name && email ? `${name} <${email}>` : name || email

    const hedgehogProfile = !!user?.hedgehog_config?.use_as_profile

    const gravatarUrl = useMemo(() => {
        if (hedgehogProfile || inStorybookTestRunner()) {
            return // There are no guarantees on how long it takes to fetch a Gravatar, so we skip this in snapshots
        }
        // Check if Gravatar exists
        const identifier = email || (name?.includes('@') ? name : undefined)
        if (identifier) {
            const hash = md5(identifier.trim().toLowerCase())
            return `https://www.gravatar.com/avatar/${hash}?s=96&d=404`
        }
    }, [email, hedgehogProfile, name])

    // Defer gravatar loading to prevent blocking initial render (especially in tables)
    // Only use internal state if loading prop not provided
    useEffect(() => {
        if (loading === undefined) {
            queueMicrotask(() => {
                setShouldLoadGravatarInternal(true)
            })
        }
    }, [loading])

    // Use loading prop if provided, otherwise fall back to internal state
    const shouldLoadGravatar = loading !== undefined ? loading : shouldLoadGravatarInternal

    const pictureComponent = (
        <span className={clsx('ProfilePicture', size, className)} ref={ref}>
            {hedgehogProfile ? (
                <HedgehogBuddyProfile {...user.hedgehog_config} size="100%" />
            ) : (
                gravatarLoaded !== true && (
                    <>
                        {type === 'bot' ? (
                            <IconRobot className="p-0.5" />
                        ) : !hedgehogProfile ? (
                            <Lettermark
                                name={combinedNameAndEmail}
                                index={index}
                                rounded
                                color={type === 'system' ? LettermarkColor.Gray : undefined}
                            />
                        ) : (
                            <HedgehogBuddyProfile {...user.hedgehog_config} size="100%" />
                        )}
                    </>
                )
            )}
            {gravatarUrl && shouldLoadGravatar && gravatarLoaded === true ? (
                <img
                    className="absolute top-0 left-0 w-full h-full rounded-full"
                    src={gravatarUrl}
                    loading="lazy"
                    title={title || `This is the Gravatar for ${combinedNameAndEmail}`}
                    alt=""
                    onError={() => setGravatarLoaded(false)}
                    onLoad={() => setGravatarLoaded(true)}
                />
            ) : null}
            {gravatarUrl && shouldLoadGravatar && gravatarLoaded === undefined ? (
                <img
                    className="hidden"
                    src={gravatarUrl}
                    loading="lazy"
                    alt=""
                    onError={() => setGravatarLoaded(false)}
                    onLoad={() => setGravatarLoaded(true)}
                />
            ) : null}
        </span>
    )

    return !showName ? (
        pictureComponent
    ) : (
        <div className="profile-package" title={combinedNameAndEmail}>
            {pictureComponent}
            <span className="profile-name">
                {currentUser?.email === email ? 'you' : name || email || 'an unknown user'}
            </span>
        </div>
    )
})
