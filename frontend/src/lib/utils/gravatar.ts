import md5 from 'md5'

// Gravatar's own entry point, not a deep link into the signed-in dashboard: those bounce
// through a WordPress.com OAuth chain with nowhere to land for a person who has no account.
export const GRAVATAR_MANAGE_URL = 'https://gravatar.com/'

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
