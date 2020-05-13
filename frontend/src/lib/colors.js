const lightColors = [
    'blue',
    'orange',
    'green',
    'red',
    'purple',
    'gray',
    'indigo',
    'pink',
    'yellow',
    'teal',
    'cyan',
    'gray-dark',
]
const getColorVar = variable => getComputedStyle(document.body).getPropertyValue('--' + variable)

export const darkWhites = [
    'rgba(255,255,255,0.6)',
    'rgba(255,255,180,0.5)',
    'rgba(180,255,255,0.4)',
    'rgba(255,255,180,0.3)',
    'rgba(180,255,255,0.2)',
]

const hueDiff = -10

export const colorsForBackground = (hue, saturation = 63, lightness = 40) => [
    `hsl(${hue + hueDiff}, ${saturation - 20}%, ${lightness + 40}%)`,
    `hsl(${hue + hueDiff}, ${saturation + 40}%, ${lightness + 20}%)`,
    `hsl(${hue + hueDiff}, ${saturation + 40}%, ${lightness - 20}%)`,
    `hsl(${hue - hueDiff}, ${saturation}%, ${lightness + 20}%)`,
    `hsl(${hue - hueDiff}, ${saturation}%, ${lightness - 20}%)`,
    `hsl(${hue - hueDiff}, ${saturation + 40}%, ${lightness + 20}%)`,
    `hsl(${hue - hueDiff}, ${saturation + 40}%, ${lightness - 20}%)`,
    `hsl(${hue - hueDiff * 6}, ${saturation}%, ${lightness}%)`,
    `hsl(${hue - hueDiff * 6}, ${saturation}%, ${lightness - 20}%)`,
    `hsl(${hue - hueDiff * 6}, ${saturation + 40}%, ${lightness + 40}%)`,
    `hsl(${hue + hueDiff * 6}, ${saturation}%, ${lightness}%)`,
    `hsl(${hue + hueDiff * 6}, ${saturation}%, ${lightness - 20}%)`,
    `hsl(${hue + hueDiff * 6}, ${saturation + 40}%, ${lightness + 40}%)`,
]

export const hsl = {
    blue: [212, 63, 40],
    purple: [249, 46, 51],
    green: [145, 60, 34],
}

export const getChartColors = backgroundColor => {
    const theme = backgroundColor === 'white' ? 'light' : 'dark'
    return hsl[backgroundColor]
        ? colorsForBackground(...hsl[backgroundColor])
        : theme === 'dark'
        ? darkWhites
        : lightColors.map(color => getColorVar(color))
}
