import { hashCodeForString, slugify } from 'lib/utils/strings'

/** The key a new category gets from its label, in the format results store: lowercase words joined by hyphens. */
export function categoryKey(label: string): string {
    const slug = slugify(label)
        .replace(/_/g, '-')
        .replace(/-{2,}/g, '-')
        .replace(/^-+|-+$/g, '')
    // Slugs keep only Latin letters and digits, so a label in another script gets a stable key from its text.
    if (!slug && /[\p{L}\p{N}]/u.test(label)) {
        return `category-${hashCodeForString(label.trim()).toString(36)}`
    }
    return slug
}
