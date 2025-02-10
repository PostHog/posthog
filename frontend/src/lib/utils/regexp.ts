export const isValidRegexp = (regex: string): boolean => {
    try {
        new RegExp(regex)
        return true
    } catch (e) {
        return false
    }
}
