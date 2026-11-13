// Markdown imported `with { type: 'text' }`, which Bun bundles into the binary as a string.
declare module '*.md' {
    const text: string
    export default text
}
