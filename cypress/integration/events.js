import decideResponse from '../fixtures/api/decide'
import { dayjs } from 'lib/dayjs'

const interceptPropertyDefinitions = () => {
    cy.intercept('api/projects/@current/property_definitions/?limit=5000', {
        fixture: 'api/event/property_definitions',
    })

    cy.intercept('/api/projects/1/property_definitions?search=&*', {
        fixture: 'api/event/property_definitions',
    })

    cy.intercept('/api/projects/1/property_definitions?search=%24time*', {
        fixture: 'api/event/only_time_property_definition',
    })

    cy.intercept('/api/projects/1/property_definitions?search=%24browser*', {
        fixture: 'api/event/only_browser_version_property_definition',
    })
}

const selectNewTimestampPropertyFilter = () => {
    cy.get('[data-attr=new-prop-filter-EventsTable]').click()
    cy.get('[data-attr=taxonomic-filter-searchfield]').type('timestamp')
    cy.get('.taxonomic-list-row').should('have.length', 1).click()
}

const selectDateTimeOperator = (operator, openPopUp) => {
    if (openPopUp) {
        cy.get('[data-attr="property-filter-0"] .property-filter .property-filter-button-label').click()
    }

    cy.get('.taxonomic-operator').click()
    cy.get('.operator-value-option').its('length').should('eql', 5)
    cy.get('.operator-value-option').contains('< before').should('be.visible')
    cy.get('.operator-value-option').contains('> after').should('be.visible')

    cy.get('.operator-value-option').contains(operator).click()
}

const changeSecondPropertyFilterToDateAfter = () => {
    selectDateTimeOperator('> after', true)
}

describe('Events', () => {
    beforeEach(() => {
        interceptPropertyDefinitions()

        cy.intercept('/api/event/values/?key=$browser_version', (req) => {
            return req.reply([{ name: '96' }, { name: '97' }])
        })

        // sometimes the system under test calls `/decide`
        // and sometimes it calls https://app.posthog.com/decide
        cy.intercept(/.*\/decide\/.*/, (req) =>
            req.reply(
                decideResponse({
                    '6619-query-events-by-date': true,
                })
            )
        ).as('featureFlagsLoaded')

        cy.visit('/events')
    })

    it('Events loaded', () => {
        cy.get('[data-attr=events-table]').should('exist')
    })

    it('Click on an event', () => {
        cy.get('[data-attr=events-table] .event-row:nth-child(2) td:first-child').click()
        cy.get('[data-attr=event-details]').should('exist')
    })

    it('Apply 1 overall filter', () => {
        cy.get('[data-attr=new-prop-filter-EventsTable]').click()
        cy.get('[data-attr=taxonomic-filter-searchfield]').click()
        cy.get('.taxonomic-infinite-list .property-key-info').contains('Browser Version').click({ force: true })
        cy.get('[data-attr=prop-val]').click()
        cy.get('[data-attr=prop-val-0]').click({ force: true })
        cy.get('[data-attr=events-table]').should('exist')
    })

    it('use before and after with a DateTime property', () => {
        cy.wait('@featureFlagsLoaded').then(() => {
            selectNewTimestampPropertyFilter()

            cy.get('.taxonomic-operator').click()
            cy.get('.operator-value-option').should('contain.text', '> after')
            cy.get('.operator-value-option').should('contain.text', '< before')
        })
    })

    it('use less than and greater than with a numeric property', () => {
        cy.get('[data-attr=new-prop-filter-EventsTable]').click()
        cy.get('[data-attr=taxonomic-filter-searchfield]').type('$browser_version')
        cy.get('.taxonomic-list-row').should('have.length', 1).click()

        cy.get('.taxonomic-operator').click()
        cy.get('.operator-value-option').its('length').should('eql', 10)
        cy.get('.operator-value-option').contains('< lower than').should('be.visible')
        cy.get('.operator-value-option').contains('> greater than').should('be.visible')
    })

    it('use before and after with a DateTime property', () => {
        cy.wait('@featureFlagsLoaded').then(() => {
            selectNewTimestampPropertyFilter()

            cy.get('.taxonomic-operator').click()
            cy.get('.operator-value-option').should('contain.text', '> after')
            cy.get('.operator-value-option').should('contain.text', '< before')
        })
    })

    it('can filter after a date and can filter before it', () => {
        cy.intercept(/api\/projects\/\d+\/events\/.*/).as('getEvents')

        selectNewTimestampPropertyFilter()

        const oneDayAgo = dayjs().hour(19).minute(1).subtract(1, 'day').format('YYYY-MM-DD HH:mm:ss')
        selectDateTimeOperator('< before', undefined)
        cy.get('.taxonomic-value-select').click()
        cy.get('.ant-picker-footer-extra button.LemonSwitch').click({ force: true })
        cy.get('.filter-date-picker').type(oneDayAgo)
        cy.get('.ant-picker-footer .ant-picker-ok button').click({ scrollBehavior: false, force: true })
        cy.get('[data-attr="property-filter-0"]').should('include.text', 'Timestamp < ')

        cy.wait('@getEvents').then(() => {
            // as the seeded events are random(-ish) it may be "a day ago" it may be "2 days ago"
            cy.get('tr.event-row:first-child').should('contain.text', 'day').should('contain.text', 'ago')
            cy.get('tr.event-row').should((rows) => {
                // test data setup is slightly random so...
                expect(rows.length).to.be.greaterThan(50)
                expect(rows.length).to.be.lessThan(110)
            })

            changeSecondPropertyFilterToDateAfter()

            cy.wait('@getEvents').then(() => {
                cy.get('[data-attr="property-filter-0"]').should('include.text', 'Timestamp > ')
                // as the seeded events are random(-ish) we can't assert on how long ago they will be
                cy.get('tr.event-row:first-child').should('not.contain.text', 'day')
                cy.get('tr.event-row').should((rows) => {
                    // test data setup is slightly random so...
                    expect(rows.length).to.be.greaterThan(5)
                    expect(rows.length).to.be.lessThan(60)
                })
            })
        })
    })
})
