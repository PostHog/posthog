/* Used for graphs line or background color (as applicable) */
export const lightColors = [
    'navy',
    'blue',
    'cyan',
    'orange',
    'yellow',
    'olive',
    'green',
    'lime',
    'mint',
    'maroon',
    'brown',
    'apricot',
    'pink',
    'salmon',
    'indigo',
    'purple',
]

export const tagColors = [
    'blue',
    'cyan',
    'orange',
    'gold',
    'green',
    'lime',
    'volcano',
    'magenta',
    'purple',
    'red',
    'geekblue',
]

const getColorVar = (variable: string): string =>
    getComputedStyle(document.body)
        .getPropertyValue('--' + variable)
        .trim()

export const darkWhites = [
    'rgba(255,255,255,0.6)',
    'rgba(255,255,180,0.5)',
    'rgba(180,255,255,0.4)',
    'rgba(255,255,180,0.3)',
    'rgba(180,255,255,0.2)',
]

const hueDiff = -10

export function colorsForBackground(hue: number, saturation = 63, lightness = 40): string[] {
    return [
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
        `hsl(${hue - hueDiff * 9}, ${saturation}%, ${lightness}%)`,
        `hsl(${hue - hueDiff * 9}, ${saturation}%, ${lightness - 20}%)`,
        `hsl(${hue - hueDiff * 9}, ${saturation + 40}%, ${lightness + 40}%)`,
        `hsl(${hue + hueDiff * 9}, ${saturation}%, ${lightness}%)`,
        `hsl(${hue + hueDiff * 9}, ${saturation}%, ${lightness - 20}%)`,
        `hsl(${hue + hueDiff * 9}, ${saturation + 40}%, ${lightness + 40}%)`,
    ]
}

export const dashboardColorNames = {
    white: 'White',
    blue: 'Blue',
    green: 'Green',
    purple: 'Purple',
    black: 'Black',
}

// update DashboardItems.scss with the color CSS variables
export const dashboardColorHSL = {
    white: [0, 0, 100],
    blue: [212, 63, 40],
    purple: [249, 46, 51],
    green: [145, 60, 34],
    black: [0, 0, 18],
}

export const cssHSL = (h: number, s: number, l: number): string =>
    `hsl(${h % 360}, ${Math.max(0, Math.min(100, s))}%, ${Math.max(0, Math.min(100, l))}%)`

export const dashboardColors: Record<string, string> = {}
Object.entries(dashboardColorHSL).forEach(([key, [h, s, l]]) => {
    dashboardColors[key] = cssHSL(h, s, l)
})

export function getChartColors(backgroundColor: string): string[] {
    if (backgroundColor === 'black') {
        const colors = []
        for (let i = 0; i < 20; i++) {
            const h = ((40 + i * 160) % 360) + (i > 10 ? 40 : 0)
            const s = i > 0 ? 30 : 10
            const l = 90 - (i % 5) * 10 //  (i % 2 === 0 ? i : (10 - i)) * 7
            colors.push(cssHSL(h, s, l))
        }
        return colors
    }

    if (backgroundColor === 'white' || !backgroundColor) {
        return lightColors.map((color) => getColorVar(color))
    }

    const colors = dashboardColorHSL[backgroundColor as keyof typeof dashboardColorHSL]

    if (colors) {
        return colorsForBackground(colors[0], colors[1], colors[2])
    }

    return darkWhites
}

export function getBarColorFromStatus(status: string, hover?: boolean): string {
    switch (status) {
        case 'new':
        case 'returning':
        case 'resurrecting':
        case 'dormant':
            return getColorVar(`lifecycle-${status}${hover ? '-hover' : ''}`)
        default:
            return 'black'
    }
}

export function getGraphColors(isLightTheme: boolean = true): Record<string, string | null> {
    return {
        axisLabel: isLightTheme ? '#333' : 'rgba(255,255,255,0.8)',
        axisLine: isLightTheme ? '#ddd' : 'rgba(255,255,255,0.2)',
        axis: isLightTheme ? '#999' : 'rgba(255,255,255,0.6)',
        crosshair: 'rgba(0,0,0,0.2)',
        tooltipBackground: '#1dc9b7',
        tooltipTitle: '#fff',
        tooltipBody: '#fff',
        annotationColor: isLightTheme ? null : 'white',
        annotationAccessoryColor: isLightTheme ? null : 'black',
    }
}
