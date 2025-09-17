const hasCapitalLetter = (text: string): boolean => /^[A-Z](.*?)$/.test(text)

const hasNumber = (text: string): boolean => /\d/.test(text)

const normalizeIdInPath = (pathChunk: string): string => {
    if (!hasNumber(pathChunk) && !hasCapitalLetter(pathChunk)) {
        return pathChunk
    }

    return ':id'
}

const removeHashSearchQuery = (path: string): string => path.split('?')[0]

export const normalizePath = (path = ''): string => {
    const decodedPath = decodeURIComponent(path)
    const myURL = new URL(decodedPath)

    const newHash = removeHashSearchQuery(myURL.hash).split('/').map(normalizeIdInPath).join('/')

    return myURL.origin + myURL.pathname + newHash
}
