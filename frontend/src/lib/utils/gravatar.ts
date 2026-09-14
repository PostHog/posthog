import md5 from 'md5'

export const GRAVATAR_MANAGE_URL = 'https://gravatar.com/profile/avatars'

// The avatars page goes straight to a sign-in wall, which is a dead end for someone who has
// no Gravatar account. The home page explains what Gravatar is and offers sign-up.
export const GRAVATAR_GET_STARTED_URL = 'https://gravatar.com/'

export function gravatarUrl(identifier: string, refreshKey?: number): string {
    const hash = md5(identifier.trim().toLowerCase())
    const url = `https://www.gravatar.com/avatar/${hash}?s=96&d=404`
    return refreshKey ? `${url}&_=${refreshKey}` : url
}

export function probeImage(url: string): Promise<boolean> {
    return new Promise((resolve) => {
        const image = new Image()
        image.onload = () => resolve(true)
        image.onerror = () => resolve(false)
        image.src = url
    })
}
