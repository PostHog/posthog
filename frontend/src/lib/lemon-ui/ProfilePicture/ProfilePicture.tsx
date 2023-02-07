import clsx from 'clsx'
import { useValues } from 'kea'
import md5 from 'md5'
import { useState } from 'react'
import { userLogic } from 'scenes/userLogic'
import { Lettermark, LettermarkColor } from '../Lettermark/Lettermark'
import './ProfilePicture.scss'

export interface ProfilePictureProps {
    name?: string
    email?: string
    size?: 'md' | 'xs' | 'sm' | 'xl' | 'xxl'
    showName?: boolean
    style?: React.CSSProperties
    className?: string
    title?: string
    index?: number
    isSystem?: boolean
}

export function ProfilePicture({
    name,
    email,
    size,
    showName,
    style,
    className,
    index,
    title,
    isSystem,
}: ProfilePictureProps): JSX.Element {
    const { user } = useValues(userLogic)
    const [didImageError, setDidImageError] = useState(false)
    const pictureClass = clsx('profile-picture', size, className)

    let pictureComponent: JSX.Element

    const combinedNameAndEmail = name && email ? `${name} <${email}>` : name || email

    if (email && !didImageError) {
        const emailHash = md5(email.trim().toLowerCase())
        const gravatarUrl = `https://www.gravatar.com/avatar/${emailHash}?s=96&d=404`
        pictureComponent = (
            <img
                className={pictureClass}
                src={gravatarUrl}
                onError={() => setDidImageError(true)}
                title={title || `This is the Gravatar for ${combinedNameAndEmail}`}
                alt=""
                style={style}
            />
        )
    } else {
        pictureComponent = (
            <span className={pictureClass} style={style}>
                <Lettermark
                    name={combinedNameAndEmail}
                    index={index}
                    rounded
                    color={isSystem ? LettermarkColor.Gray : undefined}
                />
            </span>
        )
    }
    return !showName ? (
        pictureComponent
    ) : (
        <div className="profile-package" title={combinedNameAndEmail}>
            {pictureComponent}
            <span className="profile-name">{user?.email === email ? 'you' : name || email || 'an unknown user'}</span>
        </div>
    )
}
