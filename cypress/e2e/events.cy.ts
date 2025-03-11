describe('Events', () => {
    beforeEach(() => {
        cy.intercept('/api/event/values?key=%24browser').as('getBrowserValues')

        cy.intercept('api/projects/@current/property_definitions/?limit=5000', {
            fixture: 'api/event/property_definitions',
        })

        cy.intercept('/api/projects/*/property_definitions?is_feature_flag=false&search=&*', {
            fixture: 'api/event/property_definitions',
        })

        cy.intercept('/api/projects/*/property_definitions?is_feature_flag=false&search=%24time*', {
            fixture: 'api/event/only_time_property_definition',
        })

        cy.intercept('/api/projects/*/property_definitions?is_feature_flag=false&search=%24browser*', {
            fixture: 'api/event/only_browser_version_property_definition',
        })

        cy.intercept('/api/projects/*/property_definitions?is_feature_flag=true*', {
            fixture: 'api/event/feature_flag_property_definition',
        })

        cy.intercept('/api/event/values/?key=$browser_version', (req) => {
            return req.reply([{ name: '96' }, { name: '97' }])
        })

        cy.visit('/activity/explore')
    })

    /**  keeping this because it works locally in playwright but not in CI */
    it('Click on an event', () => {
        cy.get('.DataTable [data-row-key]:nth-child(2) td:first-child').click()
        cy.get('[data-attr=event-details]').should('exist')
    })
})
