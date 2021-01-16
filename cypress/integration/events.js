describe('Events', () => {
    beforeEach(() => {
        // Before each should reset the column config to DEFAULT config
        cy.getCookie('csrftoken').then((csrftoken) => {
            cy.request({
                url: '/api/user/',
                body: { user: { events_column_config: { active: 'DEFAULT' } } },
                method: 'PATCH',
                headers: {
                    'X-CSRFToken': csrftoken.value,
                },
            })
        })
        cy.visit('/events')
    })

    it('Events loaded', () => {
        cy.get('[data-attr=events-table]').should('exist')
    })

    it('Click on an event', () => {
        cy.get('[data-attr=events-table] .event-row:nth-child(2) td:first-child').click()
        cy.get('[data-attr=event-details]').should('exist')
    })

    it('Only selected columns from column selector exists in table', () => {
        cy.get('[data-attr=events-table-column-selector]').click()
        cy.get('.items-selector-modal')
            .should('be.visible')
            .then(() => {
                cy.get('.items-selector-modal input:checked')
                    .parents('label')
                    .each(($elem) => {
                        cy.get('[data-attr=events-table] thead').within(() =>
                            cy.get('th').contains($elem.text()).should('exist')
                        )
                    })
                cy.get('.items-selector-checkbox input:not(:checked)')
                    .parents('label')
                    .each(($elem) => {
                        cy.get('[data-attr=events-table] thead').within(() =>
                            cy.get('th').contains($elem.text()).should('not.exist')
                        )
                    })
            })
    })

    it('Add columns to event table', () => {
        const newColumns = []
        let oldColumnsCount
        cy.get('[data-attr=events-table-column-selector]').click()
        cy.get('[data-attr=events-table] thead th').then(($headings) => {
            oldColumnsCount = $headings.length
        })
        cy.get('.items-selector-modal')
            .should('be.visible')
            .within(() => {
                cy.get('.items-selector-checkbox input:not(:checked)')
                    .parents('label')
                    .should('be.visible')
                    .each(($elem) => {
                        newColumns.push($elem.text())
                    })
                    .then(() => {
                        expect(newColumns).to.be.not.empty
                    })
                    .click({ multiple: true })
            })
        cy.get('.items-selector-modal .items-selector-confirm').click()
        cy.get('.items-selector-modal').should('not.be.visible')
        cy.get('[data-attr=events-table] thead').within(() => {
            cy.get('th').should('have.length.greaterThan', oldColumnsCount)
            expect(newColumns).to.be.not.empty
            newColumns.forEach((title) => {
                cy.get('th').contains(title).should('exist')
            })
        })
        cy.get('[data-attr=events-table-column-selector]').click()

        // All old and new titles should be selected in column selector modal after it opens again
        // And should be present in table
        cy.get('.items-selector-modal')
            .should('be.visible')
            .then(() => {
                cy.get('.items-selector-modal input:checked')
                    .parents('label')
                    .each(($elem) => {
                        cy.get('[data-attr=events-table] thead').within(() =>
                            cy.get('th').contains($elem.text()).should('exist')
                        )
                    })
            })
    })

    it('Remove columns from event table', () => {
        const removedColumns = []
        let oldColumnsCount
        cy.get('[data-attr=events-table-column-selector]').click()
        cy.get('[data-attr=events-table] thead th').then(($headings) => {
            oldColumnsCount = $headings.length
        })
        cy.get('.items-selector-modal')
            .should('be.visible')
            .within(() => {
                cy.get('.items-selector-checkbox input:checked')
                    .parents('label')
                    .should('be.visible')
                    .then(($checkedElems) => {
                        let numCheckboxesToUncheck = 2
                        $checkedElems.each((index, elem) => {
                            if (numCheckboxesToUncheck < index) {
                                removedColumns.push(Cypress.$(elem).text())
                                cy.wrap(Cypress.$(elem)).click()
                            }
                        })
                        expect(removedColumns).to.be.not.empty
                    })
            })
        cy.get('.items-selector-modal .items-selector-confirm').click()
        cy.get('.items-selector-modal').should('not.be.visible')
        cy.get('[data-attr=events-table] thead').within(() => {
            cy.get('th').should('have.length.lessThan', oldColumnsCount)
            expect(removedColumns).to.be.not.empty
            removedColumns.forEach((title) => {
                cy.get('th').contains(title).should('not.exist')
            })
        })
        cy.get('[data-attr=events-table-column-selector]').click()

        // All old and new titles should be selected in column selector modal after it opens again
        // And should be present in table
        cy.get('.items-selector-modal')
            .should('be.visible')
            .then(() => {
                cy.get('.items-selector-checkbox input:not(:checked)')
                    .parents('label')
                    .each(($elem) => {
                        cy.get('[data-attr=events-table] thead').within(() =>
                            cy.get('th').contains($elem.text()).should('not.exist')
                        )
                    })
            })
    })

    it('Apply 1 overall filter', () => {
        cy.get('[data-attr=new-prop-filter-EventsTable]').click()
        cy.get('[data-attr=property-filter-dropdown]').click()
        cy.get('[data-attr=prop-filter-event-0]').click({ force: true })
        cy.get('[data-attr=prop-val]').click()
        cy.get('[data-attr=prop-val-0]').click({ force: true })
        cy.get('[data-attr=events-table]').should('exist')
    })
})
