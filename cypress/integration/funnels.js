describe('Funnels', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-funnels]').click()
    })

    it('Funnels loaded', () => {
        cy.get('h1').should('contain', 'Funnels')
    })

    it('Click on a funnel', () => {
        cy.get('[data-attr=funnel-link-0]').click()
        cy.get('[data-attr=funnel-tab]').should('exist')
    })

    it('Apply date filter to funnel', () => {
        cy.get('[data-attr=funnel-link-0]').click()
        cy.get('[data-attr=funnel-tab]').should('exist')
        cy.get('[data-attr=date-filter]').click()
        cy.contains('Last 30 days').click()

        cy.get('[data-attr=funnel-viz]').should('exist')
    })

    it('Go to new funnel screen', () => {
        cy.get('[data-attr=create-funnel]').click()
        cy.get('[data-attr=funnel-tab]').should('exist')
    })

    it('Add 1 action to funnel', () => {
        cy.get('[data-attr=create-funnel]').click()
        cy.get('[data-attr=funnel-tab]').should('exist')

        cy.get('[data-attr=edit-funnel-input]').type('Test funnel')
        cy.get('[data-attr=add-action-event-button]').click()
        cy.get('[data-attr=trend-element-subject-0]').click()
        cy.contains('Pageviews').click()
        cy.get('[data-attr=save-funnel-button]', { timeout: 7000 }).click()

        cy.get('[data-attr=funnel-viz]').should('exist')
    })

    it('Add 2 actions to funnel', () => {
        cy.get('[data-attr=create-funnel]').click()
        cy.get('[data-attr=funnel-tab]').should('exist')

        cy.get('[data-attr=edit-funnel-input]').type('Test funnel')
        cy.get('[data-attr=add-action-event-button]').click()
        cy.get('[data-attr=trend-element-subject-0]').click()
        cy.contains('Pageviews').click()

        cy.get('[data-attr=add-action-event-button]').click()
        cy.get('[data-attr=trend-element-subject-1]').click()
        cy.contains('HogFlix homepage view').click()

        cy.get('[data-attr=save-funnel-button]').click()

        cy.get('[data-attr=funnel-viz]').should('exist')
    })
})
