export function dataURIOrPNG(src: string): string {
    src = src.replace(/\r?\n|\r/g, '')
    if (!src.startsWith('data:image/')) {
        return 'data:image/png;base64,' + src
    }
    return src
}
