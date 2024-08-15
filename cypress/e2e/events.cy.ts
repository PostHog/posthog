const interceptPropertyDefinitions = (): void => {
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
}

const selectNewTimestampPropertyFilter = (): void => {
    cy.get('[data-attr="new-prop-filter-EventPropertyFilters.0"]').click()
    cy.get('[data-attr=taxonomic-filter-searchfield]').type('$time')
    cy.get('.taxonomic-list-row').should('have.length', 1)
    cy.get('[data-attr=prop-filter-event_properties-0]').click({ force: true })
}

const selectOperator = (operator: string, openPopover: boolean): void => {
    if (openPopover) {
        cy.get('[data-attr="property-filter-0"] .property-filter .property-filter-button-label').click()
    }

    cy.get('[data-attr="taxonomic-operator"]').click()
    cy.get('.operator-value-option').its('length').should('eql', 8)
    cy.get('.operator-value-option').contains('< before').should('be.visible')
    cy.get('.operator-value-option').contains('> after').should('be.visible')

    cy.get('.operator-value-option').contains(operator).click()
}

const changeSecondPropertyFilterToDateAfter = (): void => {
    selectOperator('> after', true)
}

describe('Events', () => {
    beforeEach(() => {
        interceptPropertyDefinitions()

        cy.intercept('/api/event/values/?key=$browser_version', (req) => {
            return req.reply([{ name: '96' }, { name: '97' }])
        })

        cy.visit('/activity/explore')
    })

    it('Events loaded', () => {
        cy.get('.DataTable').should('exist')
    })

    it('Click on an event', () => {
        cy.get('.DataTable [data-row-key]:nth-child(2) td:first-child').click()
        cy.get('[data-attr=event-details]').should('exist')
    })

    it('Apply 1 overall filter', () => {
        cy.get('[data-attr="new-prop-filter-EventPropertyFilters.0"]').click()
        cy.get('[data-attr=taxonomic-filter-searchfield]').click()
        cy.get('[data-attr=prop-filter-event_properties-0]').click()
        cy.get('[data-attr=prop-val]').click({ force: true })
        cy.wait('@getBrowserValues').then(() => {
            cy.get('[data-attr=prop-val-0]').click()
            cy.get('.DataTable').should('exist')
        })
    })

    it('separates feature flag properties into their own tab', () => {
        cy.get('[data-attr="new-prop-filter-EventPropertyFilters.0"]').click()
        cy.get('[data-attr="taxonomic-tab-event_feature_flags"]').should('contain.text', 'Feature flags: 2').click()
        // some virtualized rows remain in the dom, but hidden
        cy.get('.taxonomic-list-row:visible').should('have.length', 2)
    })

    it('use before and after with a DateTime property', () => {
        selectNewTimestampPropertyFilter()

        cy.get('[data-attr="taxonomic-operator"]').click()
        cy.get('.operator-value-option').should('contain.text', '> after')
        cy.get('.operator-value-option').should('contain.text', '< before')
    })

    it('use less than and greater than with a numeric property', () => {
        cy.get('[data-attr="new-prop-filter-EventPropertyFilters.0"]').click()
        cy.get('[data-attr=taxonomic-filter-searchfield]').type('$browser_version')
        cy.get('.taxonomic-list-row').should('have.length', 1).click()

        cy.get('[data-attr="taxonomic-operator"]').click()
        cy.get('.operator-value-option').its('length').should('eql', 11) // 10 + 1 for the label in the LemonSelect button
        cy.get('.operator-value-option').contains('< less than').should('be.visible')
        cy.get('.operator-value-option').contains('> greater than').should('be.visible')
    })

    it('adds and removes an additional column', () => {
        cy.get('[data-attr=events-table-column-selector]').click()
        cy.get('[data-attr=taxonomic-filter-searchfield]').type('$browser_version')
        cy.get('.taxonomic-list-row').should('have.length', 1).click()
        cy.get('.SelectedColumn').should('have.length', 7)
        cy.get('[data-attr=column-display-item-remove-icon').last().click()
        cy.get('.SelectedColumn').should('have.length', 6)
    })

    it('keeps the popop open after selecting an option', () => {
        cy.get('[data-attr="new-prop-filter-EventPropertyFilters.0"]').click()
        cy.get('[data-attr=taxonomic-filter-searchfield]').type('$browser_version')
        cy.get('.taxonomic-list-row').should('have.length', 1).click()

        cy.get('[data-attr="taxonomic-operator"]').click()
        cy.get('.operator-value-option').contains('> greater than').click()
        cy.wait(500)
        cy.get('[data-attr="taxonomic-operator"]').should('be.visible')
    })

    /**
     * Test fails because property filters act on properties.$time but not all events have that property
     *
     * Needs https://github.com/PostHog/posthog/issues/8250 before can query on timestamp
     */
    it.skip('can filter after a date and can filter before it', () => {
        cy.intercept(/api\/projects\/\d+\/activity\/explore\/.*/).as('getEvents')

        selectNewTimestampPropertyFilter()

        selectOperator('< before', undefined)
        cy.get('[data-attr=taxonomic-value-select]').click()

        cy.get('[data-attr="lemon-calendar-month-previous"]').first().click()
        cy.get('[data-attr="lemon-calendar-day"]').first().click()
        cy.get('[data-attr="lemon-calendar-select-apply"]').first().click()
        cy.get('[data-attr="property-filter-0"]').should('include.text', 'Time < ')

        cy.wait('@getEvents').then(() => {
            cy.get('tr.event-row:first-child').should('contain.text', 'a day ago')
            cy.get('tr.event-row').should((rows) => {
                // test data setup is slightly random so...
                expect(rows.length).to.be.greaterThan(50)
                expect(rows.length).to.be.lessThan(110)
            })

            changeSecondPropertyFilterToDateAfter()

            cy.wait('@getEvents').then(() => {
                // as the seeded events are random(-ish) we can't assert on how long ago they will be
                cy.get('tr.event-row:first-child').should('not.contain.text', 'a day ago')
                cy.get('tr.event-row').should((rows) => {
                    // test data setup is slightly random so...
                    expect(rows.length).to.be.greaterThan(5)
                    expect(rows.length).to.be.lessThan(10)
                })
            })
        })
    })
})
