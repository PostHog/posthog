// This fixes TS errors when importing a .svg file
declare module '*.svg' {
    const content: any
    export default content
}

// This fixes TS errors when importing a .png file
declare module '*.png' {
    const content: any
    export default content
}

// This fixes TS errors when importing an .mp3 file
declare module '*.mp3' {
    const content: any
    export default content
}

// This fixes TS errors when importing chartjs-plugin-crosshair
declare module 'chartjs-plugin-crosshair' {
    const CrosshairPlugin: any
    type CrosshairOptions = any
    export { CrosshairPlugin, CrosshairOptions }
}
