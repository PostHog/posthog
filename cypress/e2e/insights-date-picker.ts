describe('insights date picker', () => {
    it('Can set the date filter and show the right grouping interval', () => {
        cy.get('[data-attr=date-filter]').click()
        cy.get('div').contains('Yesterday').should('exist').click()
        cy.get('[data-attr=interval-filter]').should('contain', 'Hour')
    })

    it('Can set a custom rolling date range', () => {
        cy.get('[data-attr=date-filter]').click()
        cy.get('[data-attr=rolling-date-range-input]').type('{selectall}5{enter}')
        cy.get('[data-attr=rolling-date-range-date-options-selector]').click()
        cy.get('.RollingDateRangeFilter__popover > div').contains('days').should('exist').click()
        cy.get('.RollingDateRangeFilter__label').should('contain', 'In the last').click()

        // Test that the button shows the correct formatted range
        cy.get('[data-attr=date-filter]').get('span').contains('Last 5 days').should('exist')
    })
})
