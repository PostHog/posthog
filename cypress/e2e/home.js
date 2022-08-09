import { reportA11y } from '../support/accessibility'

describe('Home', () => {
    it('should have no accessibility violations', () => {
        cy.get('[data-attr="menu-item-projecthomepage"]').click()
        cy.injectAxe()
        reportA11y({ includedImpacts: ['serious', 'critical'] }, 'home-page')
    })
})
