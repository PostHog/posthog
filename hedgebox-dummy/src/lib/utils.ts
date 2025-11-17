export const formatFileSize = (bytes: number): string => {
    if (bytes === 0) {return '0 Bytes'}
    const k = 1024
    const sizes = ['Bytes', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

export const getFileIcon = (type: string): string => {
    if (type.startsWith('image/')) {return '🖼️'}
    if (type.startsWith('video/')) {return '🎥'}
    if (type.startsWith('audio/')) {return '🎵'}
    if (type.includes('pdf')) {return '📄'}
    if (type.includes('word')) {return '📝'}
    if (type.includes('excel') || type.includes('spreadsheet')) {return '📊'}
    if (type.includes('powerpoint') || type.includes('presentation')) {return '📈'}
    if (type.includes('zip') || type.includes('rar')) {return '🗜️'}
    return '📁'
}
