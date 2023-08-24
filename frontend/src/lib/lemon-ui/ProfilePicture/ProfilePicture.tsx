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
    size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl' | 'xxl'
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
    size = 'lg',
    showName,
    style,
    className,
    index,
    title,
    type = 'person',
}: ProfilePictureProps): JSX.Element {
    const { user } = useValues(userLogic)
    const [gravatarUrl, setGravatarUrl] = useState<string | null>()
    const pictureClass = clsx('ProfilePicture', size, className)

    let pictureComponent: JSX.Element

    const combinedNameAndEmail = name && email ? `${name} <${email}>` : name || email

    useEffect(() => {
        // Check if Gravatar exists
        const emailOrNameWithEmail = email || (name?.includes('@') ? name : undefined)
        if (emailOrNameWithEmail) {
            const emailHash = md5(emailOrNameWithEmail.trim().toLowerCase())
            const tentativeUrl = `https://www.gravatar.com/avatar/${emailHash}?s=96&d=404`
            // The image will be cached, so it's best to do GET request check before trying to render it
            fetch(tentativeUrl)
                .then((response) => setGravatarUrl(response.status === 200 ? tentativeUrl : null))
                .catch(() => setGravatarUrl(null))
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
                <span className={pictureClass} style={style} data-picture-loading={gravatarUrl === undefined}>
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
