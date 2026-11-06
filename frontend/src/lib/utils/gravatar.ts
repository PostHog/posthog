import md5 from 'md5'

export const GRAVATAR_MANAGE_URL = 'https://gravatar.com/profile/avatars'

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
