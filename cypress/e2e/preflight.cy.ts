import { auth } from '../support'

const preflightSuccessResponse = {
    django: true,
    redis: true,
    plugins: true,
    celery: true,
    clickhouse: true,
    kafka: true,
    db: true,
    initiated: true,
    cloud: false,
    demo: false,
    realm: 'hosted-clickhouse',
    region: null,
    available_social_auth_providers: { github: false, gitlab: false, 'google-oauth2': false },
    can_create_org: true,
    email_service_available: true,
    slack_service: { available: false, client_id: null },
    object_storage: true,
}

describe('Preflight', () => {
    it('Preflight experimentation', () => {
        cy.intercept('GET', '/_preflight', preflightSuccessResponse)

        auth.logout()
        cy.visit('/preflight')

        cy.get('[data-attr=preflight-experimentation]').click()
        cy.get('[data-attr=preflight-refresh]').should('be.visible')
        cy.get('[data-attr=caption]').should('contain', 'Not required for experimentation mode')
        cy.wait(200)
        cy.get('[data-attr=preflight-complete]').should('be.visible')
        cy.get('[data-attr=preflight-complete]').click()
        cy.url().should('include', '/signup')
    })

    it('Preflight live mode', () => {
        cy.intercept('GET', '/_preflight', preflightSuccessResponse)

        auth.logout()
        cy.visit('/preflight')

        cy.get('[data-attr=preflight-live]').click()

        cy.get('.PreflightItem').should('have.length', 10)
        cy.get('[data-attr="status-text"]').filter(':contains("Validated")').should('have.length', 9)
        cy.get('[data-attr="status-text"]').filter(':contains("Warning")').should('have.length', 1)

        cy.get('[data-attr=caption]').should('contain', 'Set up before ingesting real user data')
        cy.get('[data-attr=preflight-complete]').should('be.visible')
    })

    it('Preflight can have errors too', () => {
        cy.intercept('GET', '/_preflight', { ...preflightSuccessResponse, celery: false })

        auth.logout()
        cy.visit('/preflight')

        cy.get('[data-attr=preflight-live]').click()

        cy.get('.PreflightItem').should('have.length', 10)
        cy.get('[data-attr="status-text"]').filter(':contains("Validated")').should('have.length', 8)
        cy.get('[data-attr="status-text"]').filter(':contains("Warning")').should('have.length', 1)
        cy.get('[data-attr="status-text"]').filter(':contains("Error")').should('have.length', 1)

        cy.get('[data-attr=caption]').should('contain', 'Set up before ingesting real user data')
        cy.get('[data-attr=preflight-complete]').should('not.exist')
        cy.get('.Preflight__cannot-continue')
            .filter(':contains("All required checks must pass before you can continue")')
            .should('have.length', 1)
    })
})
