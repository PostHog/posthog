export function getUploadedFile(value: unknown): File | null {
    if (!Array.isArray(value) || value.length === 0) {
        return null
    }

    const file = value[0]
    if (!file || typeof file !== 'object') {
        return null
    }

    return file as File
}
