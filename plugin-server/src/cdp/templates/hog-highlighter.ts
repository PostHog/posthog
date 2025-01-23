export const hog = (strings: TemplateStringsArray, ...values: any[]) => {
    return strings.raw[0] // Return raw string to avoid processing
}
