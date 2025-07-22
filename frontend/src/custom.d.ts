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

// This fixes TS errors when importing an .lottie file
declare module '*.lottie' {
    const content: any
    export default content
}

// This fixes TS errors when importing an .lottie file with ?url suffix
declare module '*.lottie?url' {
    const content: string
    export default content
}

// This fixes TS errors when importing an .json file
declare module '*.json' {
    const content: any
    export default content
}

// This fixes TS errors when importing an .json file with ?url suffix
declare module '*.json?url' {
    const content: any
    export default content
}
