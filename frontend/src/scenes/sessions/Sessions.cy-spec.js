import React from 'react'
import { Sessions } from './Sessions'
import * as helpers from 'cypress/support/helpers'

xdescribe('<Sessions />', () => {
    const mount = () => helpers.mountPage(<Sessions />)

    beforeEach(() => {
        cy.intercept('/_preflight/', { fixture: '_preflight' })
        cy.intercept('/api/users/@me/', { fixture: 'api/users/@me' })
        cy.intercept('/api/dashboard/', { fixture: 'api/dashboard' })
        cy.intercept('/api/personal_api_keys/', { fixture: 'api/personal_api_keys' })
        cy.intercept('/api/projects/@current/', { fixture: 'api/projects/@current' })
        cy.intercept('/api/person/properties/', { fixture: 'api/person/properties' })
        cy.interceptLazy('/api/event/sessions/', given.sessions).as('api_sessions')

        helpers.mockPosthog()
        helpers.setLocation('/sessions')
    })

    given('sessions', () => () => ({ fixture: 'api/event/sessions/demo_sessions' }))

    const iterateResponses = (responses) => {
        let call = 0
        return () => responses[call++]
    }

    describe('navigating within sessions page', () => {
        given('sessions', () =>
            iterateResponses([
                { fixture: 'api/event/sessions/demo_sessions' },
                { fixture: 'api/event/sessions/session_with_recording' },
                { fixture: 'api/event/sessions/demo_sessions' },
            ])
        )

        it('can navigate within sessions page', () => {
            mount()

            cy.contains('Sessions').should('be.visible')
            cy.wait('@api_sessions').map(helpers.getSearchParameters).should('include', {
                date_from: '2020-01-05',
                date_to: '2020-01-05',
                distinct_id: '',
                filters: '[]',
                offset: '0',
                properties: '[]',
            })

            cy.log('Play all disabled')
            cy.get('[data-attr="play-all-recordings"]').should('have.attr', 'disabled')

            cy.log('Load more should work')
            cy.get('[data-attr="load-more-sessions"]').click()
            cy.wait('@api_sessions')
                .map(helpers.getSearchParameters)
                .should('include', {
                    date_from: '2020-01-05',
                    date_to: '2020-01-05',
                    pagination: JSON.stringify({ offset: 10 }),
                })

            cy.log('Cannot load more pages')
            cy.get('[data-attr="load-more-sessions"]').should('not.exist')

            cy.log('Can navigate using calendar')
            cy.get('[data-attr="sessions-prev-date"]').click()
            cy.wait('@api_sessions').map(helpers.getSearchParameters).should('include', {
                date_from: '2020-01-04',
                date_to: '2020-01-04',
            })
        })
    })

    it('can filter sessions', () => {
        mount()
        cy.wait('@api_sessions')

        cy.get('[data-attr="sessions-filter-open"]').click()
        cy.focused().type('br').wait(150).type('{downarrow}').wait(150).type('{enter}').wait(150)
        cy.get('.sessions-filter-row input')
            .last()
            .click()
            .wait(150)
            .type('Chrome', { force: true })
            .wait(150)
            .type('{enter}', { force: true })
            .wait(150)

        cy.contains('There are unapplied filters').should('be.visible')
        cy.get('[data-attr="sessions-apply-filters"]').click()
        cy.contains('There are unapplied filters').should('not.exist')

        cy.wait('@api_sessions').map(helpers.getSearchParameters).should('include', {
            filters: '[{"type":"person","key":"$browser","value":["Chrome"],"label":"$browser","operator":"exact"}]',
        })

        cy.get('[data-attr="edit-session-filter"]').click()
        cy.focused().type('unseen').wait(150).type('{downarrow}').wait(150).type('{enter}').wait(150)
        cy.get('[data-attr="sessions-apply-filters"]').click()

        cy.wait('@api_sessions').map(helpers.getSearchParameters).should('include', {
            filters: '[{"type":"recording","key":"unseen","value":1,"label":"Unseen recordings"}]',
        })
    })

    describe('sessions with recordings', () => {
        given('sessions', () => iterateResponses([{ fixture: 'api/event/sessions/session_with_recording' }]))

        beforeEach(() => {
            cy.intercept('/api/event/session_recording', { fixture: 'api/event/session_recording' }).as(
                'api_session_recording'
            )
        })

        it('can open a session recording', () => {
            mount()

            cy.get('[data-attr="session-recordings-button"]').click()
            cy.wait('@api_session_recording').map(helpers.getSearchParameters).should('eql', {
                session_recording_id: '177902024d94f6-022e8a39d6abb8-3b710f51-1fa400-177902024da550',
                save_view: 'true',
            })

            cy.contains('19 second session on Jan 29th').should('be.visible')
            cy.contains('1276 x 1300').should('be.visible')
        })
    })

    describe('saved sessions filters', () => {
        beforeEach(() => {
            cy.intercept('/api/sessions_filter/', { fixture: 'api/sessions_filter' }).as('sessions_filter')
        })

        it('renders sessions filters', () => {
            mount()
            cy.wait('@api_sessions')
            cy.wait('@sessions_filter')

            cy.contains('Unseen recordings').should('be.visible')
            cy.contains('ChromeUsers').should('be.visible')

            cy.get('[data-attr="sessions-filter-link"]').last().click()

            cy.wait('@api_sessions')
            cy.get('@api_sessions').map(helpers.getSearchParameters).should('include', {
                filters: '[{"key":"$browser","type":"person","label":"$browser","value":"Chrome","operator":"exact"}]',
            })
        })
    })
})
