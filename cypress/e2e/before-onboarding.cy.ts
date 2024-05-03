describe('Before Onboarding', () => {
    before(() => {
        cy.request({
            method: 'PATCH',
            url: '/api/projects/1/',
            body: { completed_snippet_onboarding: false },
            headers: { Authorization: 'Bearer e2e_demo_api_key' },
        })
    })

    after(() => {
        cy.request({
            method: 'PATCH',
            url: '/api/projects/1/',
            body: { completed_snippet_onboarding: true },
            headers: { Authorization: 'Bearer e2e_demo_api_key' },
        })
    })

    it('Navigate to /products when a product has not been set up', () => {
        cy.visit('/project/1/data-management/events')

        cy.get('[data-attr=top-bar-name] > span').contains('Products')
    })

    it('Navigate to a settings page even when a product has not been set up', () => {
        cy.visit('/settings/user')

        cy.get('[data-attr=top-bar-name] > span').contains('User')

        cy.visit('/settings/organization')

        cy.get('[data-attr=top-bar-name] > span').contains('Organization')
    })
})
