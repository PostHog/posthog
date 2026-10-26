import { slugify } from 'lib/utils/strings'

/** The key a new category gets from its label, in the format results store: lowercase words joined by hyphens. */
export function categoryKey(label: string): string {
    return slugify(label)
        .replace(/_/g, '-')
        .replace(/-{2,}/g, '-')
        .replace(/^-+|-+$/g, '')
}
