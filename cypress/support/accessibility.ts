import { Options } from 'cypress-axe'

export const reportA11y = (options: Options, tag: string, skipFailures = true): void => {
    tag += '-'

    // reports on A11y failures without failing the tests
    cy.checkA11y(
        null,
        options,
        (violations) => {
            cy.log(`${violations.length} violation(s) detected`)

            cy.writeFile(`a11y/${tag}accessibility-violations.json`, JSON.stringify(violations))
        },
        skipFailures
    )
}
