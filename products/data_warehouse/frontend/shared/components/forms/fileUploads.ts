function isFileLike(file: unknown): file is File {
    if (!file || typeof file !== 'object') {
        return false
    }

    if (typeof File !== 'undefined' && file instanceof File) {
        return true
    }

    return (
        'name' in file &&
        typeof file.name === 'string' &&
        'slice' in file &&
        typeof file.slice === 'function' &&
        'arrayBuffer' in file &&
        typeof file.arrayBuffer === 'function'
    )
}

export function getUploadedFile(value: unknown): File | null {
    if (!Array.isArray(value) || value.length === 0) {
        return null
    }

    const file = value[0]
    if (!isFileLike(file)) {
        return null
    }

    return file
}
