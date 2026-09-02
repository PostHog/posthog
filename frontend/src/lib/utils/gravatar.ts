import md5 from 'md5'

export const GRAVATAR_MANAGE_URL = 'https://gravatar.com/profile/avatars'

export function gravatarUrl(identifier: string, size: number = 96): string {
    const hash = md5(identifier.trim().toLowerCase())
    return `https://www.gravatar.com/avatar/${hash}?s=${size}&d=404`
}

export function probeImage(url: string): Promise<boolean> {
    return new Promise((resolve) => {
        const image = new Image()
        image.onload = () => resolve(true)
        image.onerror = () => resolve(false)
        image.src = url
    })
}
