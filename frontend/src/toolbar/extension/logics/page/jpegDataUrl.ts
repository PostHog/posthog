/** Draws an image into a JPEG data URL, which can cross the extension port, unlike the page's object URLs. */
export async function jpegDataUrl(imageUrl: string, maxWidth: number): Promise<string> {
    const image = new Image()
    image.src = imageUrl
    await image.decode()
    const scale = Math.min(1, maxWidth / image.naturalWidth)
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(image.naturalWidth * scale)
    canvas.height = Math.round(image.naturalHeight * scale)
    canvas.getContext('2d')?.drawImage(image, 0, 0, canvas.width, canvas.height)
    return canvas.toDataURL('image/jpeg', 0.8)
}
