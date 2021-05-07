import React, { useState } from 'react'
import { IconPerson } from 'lib/components/icons'
import { PersonType } from '~/types'
import './PersonAvatar.scss'

export function PersonAvatar({ person }: { person?: Partial<PersonType> | null }): JSX.Element {
    const [hasError, setHasError] = useState(false)

    const avatar = person?.properties ? person.properties.avatar : null

    if (avatar && isValidUrl(avatar) && !hasError) {
        return (
            <img
                className="person-avatar"
                src={avatar}
                onError={() => {
                    setHasError(true)
                }}
            />
        )
    }

    return <IconPerson />
}

const isValidUrl = (url: string): boolean => {
    try {
        new URL(url)
        return true
    } catch {
        return false
    }
}
