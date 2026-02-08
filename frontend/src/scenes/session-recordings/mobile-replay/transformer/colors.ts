// from https://gist.github.com/t1grok/a0f6d04db569890bcb57

interface rgb {
    r: number
    g: number
    b: number
}
interface yuv {
    y: number
    u: number
    v: number
}

function hexToRgb(hexColor: string): rgb | null {
    const shorthandRegex = /^#?([a-f\d])([a-f\d])([a-f\d])$/i
    hexColor = hexColor.replace(shorthandRegex, function (_, r, g, b) {
        return r + r + g + g + b + b
    })

    const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hexColor)
    return result
        ? {
              r: parseInt(result[1], 16),
              g: parseInt(result[2], 16),
              b: parseInt(result[3], 16),
          }
        : null
}

function rgbToYuv(rgbColor: rgb): yuv {
    let y, u, v

    y = rgbColor.r * 0.299 + rgbColor.g * 0.587 + rgbColor.b * 0.114
    u = rgbColor.r * -0.168736 + rgbColor.g * -0.331264 + rgbColor.b * 0.5 + 128
    v = rgbColor.r * 0.5 + rgbColor.g * -0.418688 + rgbColor.b * -0.081312 + 128

    y = Math.floor(y)
    u = Math.floor(u)
    v = Math.floor(v)

    return { y: y, u: u, v: v }
}

export const isLight = (hexColor: string): boolean => {
    const rgbColor = hexToRgb(hexColor)
    if (!rgbColor) {
        return false
    }
    const yuvColor = rgbToYuv(rgbColor)
    return yuvColor.y > 128
}
