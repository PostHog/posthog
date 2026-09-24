import { Setting } from './types'

/**
 * React keys for the rendered settings blocks. An array index shifts as soon as a setting is
 * filtered in or out, and every block after it remounts, so a half-typed field loses its value.
 * A few setting ids are used in more than one section of the same level, so repeats get a suffix.
 */
export function getSettingKeys(settings: Setting[]): string[] {
    const seen = new Map<string, number>()
    return settings.map(({ id }) => {
        const repeat = seen.get(id) ?? 0
        seen.set(id, repeat + 1)
        return repeat ? `${id}-${repeat}` : id
    })
}
