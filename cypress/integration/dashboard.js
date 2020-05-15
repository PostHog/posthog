describe('Dashboards', () => {
    it('Click dashboard menu item', () => {
        cy.get(':nth-child(3) > .ant-menu-submenu-title').click()
    })
})
