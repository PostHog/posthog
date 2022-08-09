export const reportA11y = (options, tag) => {
    if (typeof tag !== undefined) {
        tag += '-'
    }

    // reports on A11y failures without failing the tests
    cy.checkA11y(
        null,
        options,
        (violations) => {
            cy.log(`${violations.length} violation(s) detected`)

            cy.writeFile(
                `a11y/${tag}${new Date().toISOString()}-accessibility-violations.json`,
                JSON.stringify(violations)
            )
        },
        true
    )
}
