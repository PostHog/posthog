import clsx from 'clsx'
import { useValues } from 'kea'
import md5 from 'md5'
import { CSSProperties, useEffect, useState } from 'react'
import { userLogic } from 'scenes/userLogic'
import { IconRobot } from '../icons'
import { Lettermark, LettermarkColor } from '../Lettermark/Lettermark'
import './ProfilePicture.scss'

export interface ProfilePictureProps {
    name?: string
    email?: string
    size?: 'md' | 'xs' | 'sm' | 'xl' | 'xxl'
    showName?: boolean
    style?: CSSProperties
    className?: string
    title?: string
    index?: number
    type?: 'person' | 'bot' | 'system'
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
    type = 'person',
}: ProfilePictureProps): JSX.Element {
    const { user } = useValues(userLogic)
    const [gravatarUrl, setGravatarUrl] = useState<string | null>(null)
    const pictureClass = clsx('profile-picture', size, className)

    let pictureComponent: JSX.Element

    const combinedNameAndEmail = name && email ? `${name} <${email}>` : name || email

    useEffect(() => {
        // Check if Gravatar exists
        const emailOrNameWithEmail = email || (name?.includes('@') ? name : undefined)
        if (emailOrNameWithEmail) {
            const emailHash = md5(emailOrNameWithEmail.trim().toLowerCase())
            const tentativeUrl = `https://www.gravatar.com/avatar/${emailHash}?s=96&d=404`
            // The image will be cached, so it's better to do a full GET request in this check
            fetch(tentativeUrl).then((response) => {
                if (response.status === 200) {
                    setGravatarUrl(tentativeUrl)
                }
            })
        }
    }, [email])

    if (gravatarUrl) {
        pictureComponent = (
            <img
                className={pictureClass}
                src={gravatarUrl}
                title={title || `This is the Gravatar for ${combinedNameAndEmail}`}
                alt=""
                style={style}
            />
        )
    } else {
        pictureComponent =
            type === 'bot' ? (
                <IconRobot className={clsx(pictureClass, 'p-0.5')} />
            ) : (
                <span className={pictureClass} style={style}>
                    <Lettermark
                        name={combinedNameAndEmail}
                        index={index}
                        rounded
                        color={type === 'system' ? LettermarkColor.Gray : undefined}
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
