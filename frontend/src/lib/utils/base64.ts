export const base64Encode = (str: string): string => {
    const data = new TextEncoder().encode(str)
    const binString = Array.from(data, (byte) => String.fromCharCode(byte)).join('')
    return btoa(binString)
}

export const base64Decode = (encodedString: string): string => {
    const data = base64ToUint8Array(encodedString)
    return new TextDecoder().decode(data)
}

export const base64ArrayBuffer = (encodedString: string): ArrayBufferLike => {
    const data = base64ToUint8Array(encodedString)
    return data.buffer
}

export const base64ToUint8Array = (encodedString: string): Uint8Array => {
    const binString = atob(encodedString)
    const data = new Uint8Array(binString.length)
    for (let i = 0; i < binString.length; i++) {
        data[i] = binString.charCodeAt(i)
    }
    return data
}
