const UUID_REGEX = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi

/**
 * Helper method that takes an object and replaces all UUIDs with placeholders
 */
export const forSnapshot = (obj: any) => {
    const idMap: Record<string, string> = {}
    let strData = JSON.stringify(obj)

    const matches = strData.match(UUID_REGEX)

    for (const match of matches ?? []) {
        idMap[match] = `<REPLACED-UUID-${Object.keys(idMap).length}>`
        strData = strData.replace(match, idMap[match])
    }

    return JSON.parse(strData)
}
