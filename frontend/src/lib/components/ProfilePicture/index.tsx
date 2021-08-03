import md5 from 'md5'
import React, { useState } from 'react'
import './ProfilePicture.scss'

export interface ProfilePictureProps {
    name?: string
    email?: string
    size?: 'md' | 'sm'
}

export function ProfilePicture({ name, email, size }: ProfilePictureProps): JSX.Element {
    const [didImageError, setDidImageError] = useState(false)
    const pictureClass = `profile-picture${size ? ` ${size}` : ''}`

    if (email && !didImageError) {
        const emailHash = md5(email.trim().toLowerCase())
        const gravatarUrl = `https://www.gravatar.com/avatar/${emailHash}?s=96&d=404`
        return (
            <img
                className={pictureClass}
                src={gravatarUrl}
                onError={() => setDidImageError(true)}
                title={`This is ${email}'s Gravatar.`}
                alt=""
            />
        )
    } else if (name) {
        return <div className={pictureClass}>{name[0]?.toUpperCase()}</div>
    } else if (email) {
        return <div className={pictureClass}>{email[0]?.toUpperCase()}</div>
    }
    return <div className={pictureClass}>?</div>
}
