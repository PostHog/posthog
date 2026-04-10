import clsx, { type ClassValue } from 'clsx'

export function cn(...inputs: ClassValue[]): string {
    return clsx(inputs)
}

export function formatDate(iso: string, includeTime = false): string {
    try {
        const options: Intl.DateTimeFormatOptions = {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            ...(includeTime ? { hour: '2-digit', minute: '2-digit' } : {}),
        }
        return new Date(iso).toLocaleDateString(undefined, options)
    } catch {
        return iso
    }
}
