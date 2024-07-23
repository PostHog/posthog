import { reportA11y } from '../support/accessibility'

describe('a11y', () => {
    it('home should have no accessibility violations', () => {
        cy.get('[data-attr="menu-item-projecthomepage"]').click()
        cy.injectAxe()
        reportA11y({ includedImpacts: ['critical'] }, 'home-page-critical', true)
        reportA11y({ includedImpacts: ['serious'] }, 'home-page-serious', true)
    })

    const sidebarItems = [
        'dashboards',
        'savedinsights',
        'replay',
        'featureflags',
        'experiments',
        'activity',
        'datamanagement',
        'personsmanagement',
        'pipeline',
        'toolbarlaunch',
        'settings',
    ]

    sidebarItems.forEach((sideBarItem) => {
        it(`${sideBarItem} should have no accessibility violations`, () => {
            cy.clickNavMenu(sideBarItem)
            cy.injectAxe()
            reportA11y({ includedImpacts: ['serious', 'critical'] }, sideBarItem)
        })
    })
})
