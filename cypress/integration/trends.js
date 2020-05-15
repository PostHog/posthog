describe('Trends', () => {
    it('Load default page', () => {
        cy.get('.ant-tabs-tabpane-active > :nth-child(1) > .ant-btn').click()
        cy.get(':nth-child(2) > .filter-action').click()
        cy.contains('Pageviews').click()
    })
})
