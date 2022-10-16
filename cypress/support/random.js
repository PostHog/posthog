export function randomString(prefix = '') {
    const uuid = () => Cypress._.random(0, 1e6)
    return `${prefix}${uuid()}`
}
