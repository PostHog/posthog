// eslint-disable-next-line no-restricted-imports
import { type ClassValue, clsx } from 'clsx'
// eslint-disable-next-line no-restricted-imports
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]): string {
    return twMerge(clsx(inputs))
}
