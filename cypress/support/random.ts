export function randomString(prefix = ''): string {
    const uuid = (): number => Cypress._.random(0, 1e6)
    return `${prefix}${uuid()}`
}
