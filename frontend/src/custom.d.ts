// This fixes TS errors when importing a .svg file
declare module '*.svg' {
    const content: any
    export default content
}
