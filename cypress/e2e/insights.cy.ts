import { urls } from 'scenes/urls'
import { randomString } from '../support/random'
import { decideResponse } from '../fixtures/api/decide'
import { savedInsights, createInsight, insight } from '../productAnalytics'

const hogQLQuery = `select event,
          count()
     from events
 group by event,
          properties.$browser,
          person.properties.email
 order by count() desc
    limit 2`

// For tests related to trends please check trendsElements.js
describe('Insights', () => {
    beforeEach(() => {
        cy.intercept('https://app.posthog.com/decide/*', (req) =>
            req.reply(
                decideResponse({
                    hogql: true,
                    'data-exploration-insights': true,
                })
            )
        )

        cy.visit(urls.insightNew())
    })

    it('Saving an insight sets breadcrumbs', () => {
        createInsight('insight name')

        cy.get('[data-attr=breadcrumb-0]').should('contain', 'Hogflix')
        cy.get('[data-attr=breadcrumb-1]').should('contain', 'Hogflix Demo App')
        cy.get('[data-attr=breadcrumb-2]').should('have.text', 'Insights')
        cy.get('[data-attr=breadcrumb-3]').should('have.text', 'insight name')
    })

    it('Can change insight name', () => {
        const startingName = randomString('starting-value-')
        const editedName = randomString('edited-value-')
        createInsight(startingName)
        cy.get('[data-attr="insight-name"]').should('contain', startingName)

        cy.get('[data-attr="insight-name"] [data-attr="edit-prop-name"]').click()
        cy.get('[data-attr="insight-name"] input').type(editedName)
        cy.get('[data-attr="insight-name"] [title="Save"]').click()

        cy.get('[data-attr="insight-name"]').should('contain', editedName)

        savedInsights.checkInsightIsInListView(editedName)
    })

    it('Can undo a change of insight name', () => {
        createInsight('starting value')
        cy.get('[data-attr="insight-name"]').should('contain', 'starting value')

        cy.get('[data-attr="insight-name"]').scrollIntoView()
        cy.get('[data-attr="insight-name"] [data-attr="edit-prop-name"]').click({ force: true })
        cy.get('[data-attr="insight-name"] input').type('edited value')
        cy.get('[data-attr="insight-name"] [title="Save"]').click()

        cy.get('[data-attr="insight-name"]').should('contain', 'edited value')

        cy.get('[data-attr="edit-insight-undo"]').click()

        cy.get('[data-attr="insight-name"]').should('not.contain', 'edited value')
        cy.get('[data-attr="insight-name"]').should('contain', 'starting value')

        savedInsights.checkInsightIsInListView('starting value')
    })

    it('Create new insight and save and continue editing', () => {
        cy.intercept('PATCH', /\/api\/projects\/\d+\/insights\/\d+\/?/).as('patchInsight')

        const insightName = randomString('insight-name-')
        createInsight(insightName)

        cy.get('[data-attr="insight-edit-button"]').click()

        cy.url().should('match', /insights\/[\w\d]+\/edit/)

        cy.get('.page-title').then(($pageTitle) => {
            const pageTitle = $pageTitle.text()

            cy.get('[data-attr="add-action-event-button"]').click()
            cy.get('[data-attr="trend-element-subject-1"]').click()
            cy.get('[data-attr="prop-filter-events-0"]').click()
            cy.get('[data-attr="insight-save-dropdown"]').click()
            cy.get('[data-attr="insight-save-and-continue"]').click()
            cy.wait('@patchInsight')
            // still on the insight edit page
            expect(pageTitle).to.eq($pageTitle.text())
            cy.get('[data-attr="insight-save-button"]').should('exist')
        })

        savedInsights.checkInsightIsInListView(insightName)
    })

    describe('unsaved insights confirmation', () => {
        it('can move away from an unchanged new insight without confirm()', () => {
            insight.newInsight()
            cy.log('Navigate away')
            cy.get('[data-attr="menu-item-featureflags"]').click()
            cy.log('We should be on the Feature Flags page now')
            cy.url().should('include', '/feature_flags')
        })

        it('Can navigate away from unchanged saved insight without confirm()', () => {
            const insightName = randomString('to save and then navigate away from')
            insight.create(insightName)

            cy.get('[data-attr="menu-item-annotations"]').click()

            // the annotations API call is made before the annotations page loads, so we can't wait for it
            cy.get('[data-attr="annotations-table"]').should('exist')
            cy.url().should('include', '/annotations')
        })

        it('Can keep editing changed new insight after navigating away with confirm() rejection (case 1)', () => {
            cy.on('window:confirm', () => {
                return false
            })

            insight.newInsight()
            cy.log('Add series')
            cy.get('[data-attr=add-action-event-button]').click()
            cy.log('Navigate away')
            cy.get('[data-attr="menu-item-featureflags"]').click()
            cy.log('Save button should still be here because case 1 rejects confirm()')
            cy.get('[data-attr="insight-save-button"]').should('exist')
        })

        it('Can navigate away from changed new insight with confirm() acceptance (case 2)', () => {
            cy.on('window:confirm', () => {
                return true
            })
            insight.newInsight()
            cy.log('Add series')
            cy.get('[data-attr=add-action-event-button]').click()
            cy.log('Navigate away')
            cy.get('[data-attr="menu-item-featureflags"]').click()
            cy.url().should('include', '/feature_flags')
        })
    })

    it('Shows not found error with invalid short URL', () => {
        cy.visit('/i/i_dont_exist')
        cy.location('pathname').should('eq', '/insights/i_dont_exist')
        cy.get('.LemonSkeleton').should('exist')
    })

    it('Stickiness graph', () => {
        cy.get('[role=tab]').contains('Stickiness').click()
        cy.get('[data-attr=add-action-event-button]').click()
        cy.get('[data-attr=trend-element-subject-1]').should('exist')
        cy.get('[data-attr=trend-line-graph]').should('exist')
        cy.get('[data-attr=add-breakdown-button]').should('not.exist') // Can't do breakdown on this graph
    })

    it('Lifecycle graph', () => {
        cy.get('[data-attr=trend-line-graph]').should('exist') // Wait until components are loaded
        cy.get('[role=tab]').contains('Lifecycle').click()
        cy.get('div').contains('Lifecycle Toggles').should('exist')
        cy.get('[data-attr=trend-line-graph]').should('exist')
        cy.get('[data-attr=add-breakdown-button]').should('not.exist') // Can't do breakdown on this graph
        cy.get('[data-attr=add-action-event-button]').should('not.exist') // Can't add multiple series
    })

    it('Loads default filters correctly', () => {
        // Test that default params are set correctly even if the app doesn't start on insights
        cy.visit('/events/') // Should work with trailing slash just like without it
        cy.reload()

        cy.clickNavMenu('insight')
        cy.get('[data-attr="menu-item-insight"]').click()
        cy.get('[data-attr=trend-element-subject-0] span').should('contain', 'Pageview')
        cy.get('[data-attr=trend-line-graph]').should('exist')
        cy.contains('Add graph series').click()
        cy.get('[data-attr=trend-element-subject-1]').should('exist')
        cy.get('[data-attr=trend-line-graph]').should('exist')
    })

    it('Cannot see tags or description (non-FOSS feature)', () => {
        cy.get('.insight-description').should('not.exist')
        cy.get('[data-attr=insight-tags]').should('not.exist')
    })

    describe('insights date picker', () => {
        it('Can set the date filter and show the right grouping interval', () => {
            cy.get('[data-attr=date-filter]').click()
            cy.get('div').contains('Yesterday').should('exist').click()
            cy.get('[data-attr=interval-filter]').should('contain', 'Hour')
        })

        it('Can set a custom rolling date range', () => {
            cy.get('[data-attr=date-filter]').click()
            cy.get('[data-attr=rolling-date-range-input]').type('{selectall}5{enter}')
            cy.get('[data-attr=rolling-date-range-date-options-selector]').click()
            cy.get('.RollingDateRangeFilter__popover > div').contains('days').should('exist').click()
            cy.get('.RollingDateRangeFilter__label').should('contain', 'In the last').click()

            // Test that the button shows the correct formatted range
            cy.get('[data-attr=date-filter]').get('span').contains('Last 5 days').should('exist')
        })
    })

    describe('duplicating insights', () => {
        let insightName
        beforeEach(() => {
            cy.visit(urls.savedInsights()) // make sure turbo mode has cached this page
            insightName = randomString('insight-name-')
            createInsight(insightName)
        })
        it('can duplicate insights from the insights list view', () => {
            cy.visit(urls.savedInsights())
            cy.contains('.saved-insights table tr', insightName).within(() => {
                cy.get('[data-attr="more-button"]').click()
            })
            cy.get('[data-attr="duplicate-insight-from-list-view"]').click()
            cy.contains('.saved-insights table tr', `${insightName} (copy)`).should('exist')
        })

        it('can duplicate insights from the insights card view', () => {
            cy.visit(urls.savedInsights())
            cy.contains('.saved-insights .LemonSegmentedButton', 'Cards').click()
            cy.contains('.CardMeta', insightName).within(() => {
                cy.get('[data-attr="more-button"]').click()
            })
            cy.get('[data-attr="duplicate-insight-from-card-list-view"]').click()
            cy.contains('.CardMeta', `${insightName} (copy)`).should('exist')
        })

        it('can duplicate from insight view', () => {
            cy.get('.page-buttons [data-attr="more-button"]').click()
            cy.get('[data-attr="duplicate-insight-from-insight-view"]').click()
            cy.get('[data-attr="insight-name"]').should('contain', `${insightName} (copy)`)

            savedInsights.checkInsightIsInListView(`${insightName} (copy)`)
        })

        it('can save insight as a copy', () => {
            cy.get('[data-attr="insight-edit-button"]').click()

            cy.get('[data-attr="insight-save-dropdown"]').click()
            cy.get('[data-attr="insight-save-as-new-insight"]').click()
            cy.get('.ant-modal-content .ant-btn-primary').click()
            cy.get('[data-attr="insight-name"]').should('contain', `${insightName} (copy)`)

            savedInsights.checkInsightIsInListView(`${insightName} (copy)`)
        })
    })

    describe('navigation', () => {
        it('can save and load and edit a SQL insight', () => {
            insight.newInsight('SQL')
            const insightName = randomString('SQL insight')
            insight.editName(insightName)
            insight.save()
            cy.visit(urls.savedInsights())
            cy.contains('.row-name a', insightName).click()

            cy.get('[data-attr="hogql-query-editor"]').should('not.exist')
            cy.get('tr.DataTable__row').should('have.length.gte', 2)

            cy.get('[data-attr="insight-edit-button"]').click()
            insight.clickTab('RETENTION')

            cy.get('[data-attr="insight-save-button"]').click()

            cy.get('.RetentionContainer canvas').should('exist')
            cy.get('.RetentionTable__Tab').should('have.length', 66)
        })

        describe('opening a new insight directly', () => {
            it('can open a new trends insight', () => {
                insight.newInsight('TRENDS')
                cy.get('.trends-insights-container canvas').should('exist')
                cy.get('tr').should('have.length.gte', 2)
            })

            it('can open a new funnels insight', () => {
                insight.newInsight('FUNNELS')
                cy.get('.funnels-empty-state__title').should('exist')
            })

            it.skip('can open a new retention insight', () => {
                insight.newInsight('RETENTION')
                cy.get('.RetentionContainer canvas').should('exist')
                cy.get('.RetentionTable__Tab').should('have.length', 66)
            })

            it('can open a new paths insight', () => {
                insight.newInsight('PATHS')
                cy.get('.Paths g').should('have.length.gte', 5) // not a fixed value unfortunately
            })

            it('can open a new stickiness insight', () => {
                insight.newInsight('STICKINESS')
                cy.get('.trends-insights-container canvas').should('exist')
            })

            it('can open a new lifecycle insight', () => {
                insight.newInsight('LIFECYCLE')
                cy.get('.trends-insights-container canvas').should('exist')
            })

            it('can open a new SQL insight', () => {
                insight.newInsight('SQL')
                insight.updateQueryEditorText(hogQLQuery, 'hogql-query-editor')
                cy.get('[data-attr="hogql-query-editor"]').should('exist')
                cy.get('tr.DataTable__row').should('have.length.gte', 2)
            })
        })

        describe('opening a new insight after opening a new SQL insight', () => {
            // TRICKY: these tests have identical assertions to the ones above, but we need to open a SQL insight first
            // and then click a different tab to switch to that insight.
            // this is because we had a bug where doing that would mean after starting to load the new insight,
            // the SQL insight would be unexpectedly re-selected and the page would switch back to it

            beforeEach(() => {
                insight.newInsight('SQL')
                insight.updateQueryEditorText(hogQLQuery, 'hogql-query-editor')
                cy.get('[data-attr="hogql-query-editor"]').should('exist')
                cy.get('tr.DataTable__row').should('have.length.gte', 2)
            })

            it('can open a new trends insight', () => {
                insight.clickTab('TRENDS')
                cy.get('.trends-insights-container canvas').should('exist')
                cy.get('tr').should('have.length.gte', 2)
                cy.contains('tr', 'No insight results').should('not.exist')
            })

            it('can open a new funnels insight', () => {
                insight.clickTab('FUNNELS')
                cy.get('.funnels-empty-state__title').should('exist')
            })

            it('can open a new retention insight', () => {
                insight.clickTab('RETENTION')
                cy.get('.RetentionContainer canvas').should('exist')
                cy.get('.RetentionTable__Tab').should('have.length', 66)
            })

            it('can open a new paths insight', () => {
                insight.clickTab('PATH')
                cy.get('.Paths g').should('have.length.gte', 5) // not a fixed value unfortunately
            })

            it('can open a new stickiness insight', () => {
                insight.clickTab('STICKINESS')
                cy.get('.trends-insights-container canvas').should('exist')
            })

            it('can open a new lifecycle insight', () => {
                insight.clickTab('LIFECYCLE')
                cy.get('.trends-insights-container canvas').should('exist')
            })

            it('can open a new SQL insight', () => {
                insight.clickTab('SQL')
                insight.updateQueryEditorText(hogQLQuery, 'hogql-query-editor')
                cy.get('[data-attr="hogql-query-editor"]').should('exist')
                cy.get('tr.DataTable__row').should('have.length.gte', 2)
            })
        })

        it('can open a new SQL insight and navigate to a different one, then back to SQL, and back again', () => {
            /**
             * This is here as a regression test. We had a bug where navigating to a new query based insight,
             * then clicking on the trends tab, then on SQL, and again on trends would mean that the trends
             * tab would be selected, but no data loaded for it 🤷‍♀️
             */

            insight.newInsight('SQL')
            cy.get('[data-attr="hogql-query-editor"]').should('exist')
            insight.updateQueryEditorText(hogQLQuery, 'hogql-query-editor')

            cy.get('.DataTable tr').should('have.length.gte', 2)

            insight.clickTab('TRENDS')
            cy.get('.trends-insights-container canvas').should('exist')
            cy.get('tr').should('have.length.gte', 2)
            cy.contains('tr', 'No insight results').should('not.exist')

            insight.clickTab('SQL')
            cy.get('[data-attr="hogql-query-editor"]').should('exist')
            insight.updateQueryEditorText(hogQLQuery, 'hogql-query-editor')

            cy.get('.DataTable tr').should('have.length.gte', 2)

            insight.clickTab('TRENDS')
            cy.get('.trends-insights-container canvas').should('exist')
            cy.get('tr').should('have.length.gte', 2)
            cy.contains('tr', 'No insight results').should('not.exist')
        })

        it('can open event explorer as an insight', () => {
            cy.clickNavMenu('events')
            cy.get('[data-attr="open-json-editor-button"]').click()
            cy.get('[data-attr="insight-json-tab"]').should('exist')
        })

        it('does not show the json tab usually', () => {
            cy.clickNavMenu('savedinsights')
            cy.get('[data-attr="insight-json-tab"]').should('not.exist')
        })
    })

    describe('view source', () => {
        it('can open the query editor', () => {
            insight.newInsight('TRENDS')
            cy.get('[aria-label="View source (BETA)"]').click()
            cy.get('[data-attr="query-editor"]').should('exist')
        })
    })
})
