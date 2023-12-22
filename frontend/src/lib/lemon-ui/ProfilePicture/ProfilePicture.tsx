import './ProfilePicture.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import { fullName, inStorybookTestRunner } from 'lib/utils'
import md5 from 'md5'
import { useMemo, useState } from 'react'
import { userLogic } from 'scenes/userLogic'

import { UserBasicType } from '~/types'

import { IconRobot } from '../icons'
import { Lettermark, LettermarkColor } from '../Lettermark/Lettermark'

export interface ProfilePictureProps {
    user?: Pick<Partial<UserBasicType>, 'first_name' | 'email' | 'last_name'> | null
    name?: string
    size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl' | 'xxl'
    showName?: boolean
    className?: string
    title?: string
    index?: number
    type?: 'person' | 'bot' | 'system'
}

export function ProfilePicture({
    user,
    name,
    size = 'lg',
    showName,
    className,
    index,
    title,
    type = 'person',
}: ProfilePictureProps): JSX.Element {
    const { user: currentUser } = useValues(userLogic)
    const [gravatarLoaded, setGravatarLoaded] = useState<boolean | undefined>()

    let email = user?.email

    if (user) {
        name = fullName(user)
        email = user.email
    }

    const combinedNameAndEmail = name && email ? `${name} <${email}>` : name || email

    const gravatarUrl = useMemo(() => {
        if (inStorybookTestRunner()) {
            return // There are no guarantees on how long it takes to fetch a Gravatar, so we skip this in snapshots
        }
        // Check if Gravatar exists
        const emailOrNameWithEmail = email || (name?.includes('@') ? name : undefined)
        if (emailOrNameWithEmail) {
            const emailHash = md5(emailOrNameWithEmail.trim().toLowerCase())
            return `https://www.gravatar.com/avatar/${emailHash}?s=96&d=404`
        }
    }, [email])

    const pictureComponent = (
        <span className={clsx('ProfilePicture', size, className)}>
            {gravatarLoaded !== true && (
                <>
                    {type === 'bot' ? (
                        <IconRobot className={'p-0.5'} />
                    ) : (
                        <Lettermark
                            name={combinedNameAndEmail}
                            index={index}
                            rounded
                            color={type === 'system' ? LettermarkColor.Gray : undefined}
                        />
                    )}
                </>
            )}
            {gravatarUrl && gravatarLoaded !== false ? (
                <img
                    className={'absolute top-0 left-0 w-full h-full rounded-full'}
                    src={gravatarUrl}
                    title={title || `This is the Gravatar for ${combinedNameAndEmail}`}
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
}
