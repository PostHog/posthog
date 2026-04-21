import { clsx, type ClassValue } from 'clsx'
import { extendTailwindMerge } from 'tailwind-merge'

const twMerge = extendTailwindMerge({
    extend: {
        classGroups: {
            'font-size': [{ text: ['xxs'] }],
        },
    },
})

export function cn(...inputs: ClassValue[]): string {
    return twMerge(clsx(inputs))
}
