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
