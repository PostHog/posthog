import { urls } from 'scenes/urls'
import { FEATURE_FLAGS } from 'lib/constants'

import { decideResponse } from 'cypress/fixtures/api/decide'

const variants = [
    { describe: 'Insights', featureFlagDataExploration: false },
    { describe: 'Insights (data exploration)', featureFlagDataExploration: true },
]

variants.forEach((variant) => {
    describe(variant.describe, () => {
        beforeEach(() => {
            cy.intercept('https://app.posthog.com/decide/*', (req) =>
                req.reply(
                    decideResponse({
                        // set feature flag
                        [FEATURE_FLAGS.DATA_EXPLORATION_INSIGHTS]: variant.featureFlagDataExploration,
                    })
                )
            )

            cy.visit(urls.insightNew())
        })

        describe('Lifecycle insight', () => {
            beforeEach(() => {
                cy.intercept('GET', /\/api\/projects\/\d+\/insights\/trend.*/, (req) => {
                    if (req.query.insight === 'LIFECYCLE') {
                        req.alias = 'getLifecycleInsight'
                    }
                })
                cy.get('[data-attr=trend-line-graph]').should('exist') // Wait until components are loaded
                cy.get('.ant-tabs-tab').contains('Lifecycle').click()
            })

            it('displays ui', () => {
                /*
                 * filters on left side
                 */
                // series
                cy.get('[data-attr=lifecycle-series-label]').contains('Showing Unique users who did').should('exist')
                cy.get('[data-attr=trend-element-subject-0]').should('exist')
                cy.get('[data-attr=add-action-event-button]').should('not.exist') // Can't add multiple series

                /*
                 * filters on right side
                 */
                // filters
                cy.get('label').contains('Filters').should('exist')
                cy.get('label').contains('Filter out internal and test users').should('exist')
                cy.get('[data-attr=insight-filters-add-filter-group]').should('not.exist') // Can't add global filters

                // lifecycle toggles
                cy.get('label').contains('Lifecycle Toggles').should('exist')
                if (variant.featureFlagDataExploration) {
                    cy.get('label').contains('New').should('exist')
                    cy.get('label').contains('Returning').should('exist')
                    cy.get('label').contains('Resurrecting').should('exist')
                    cy.get('label').contains('Dormant').should('exist')
                }

                // breakdown
                cy.get('[data-attr=add-breakdown-button]').should('not.exist') // Can't do breakdown on this insight

                /*
                 * filters in card header
                 */
                // date range
                cy.get('[data-attr=date-filter]').should('exist')
                // interval
                cy.get('[data-attr=interval-filter]').should('exist')
                // compare against previous
                cy.get('#compare-filter').should('not.exist')

                /*
                 * filters in card body
                 */
                // refresh
                cy.get('button').contains('Refresh').should('exist')
            })

            it('loads with defaults', () => {
                cy.wait('@getLifecycleInsight').then(({ request, response }) => {
                    expect(request.query.shown_as).to.eq('Lifecycle')
                    expect(request.query.events).to.be.oneOf([
                        '[{"id":"$pageview","name":"$pageview","type":"events","order":0,"math":"total"}]',
                        '[{"type":"events","id":"$pageview","name":"$pageview","math":"total"}]', // data exploration
                    ])

                    expect(response.body.result[0]).to.include({ status: 'new', count: 2 })
                    expect(response.body.result[1]).to.include({ status: 'dormant', count: -99 })
                    expect(response.body.result[2]).to.include({ status: 'resurrecting', count: 92 })
                    expect(response.body.result[3]).to.include({ status: 'returning', count: 0 })
                })
            })

            it('handles series change', () => {
                cy.wait('@getLifecycleInsight')

                // change to action
                cy.get('[data-attr=trend-element-subject-0]').click()
                cy.get('[data-attr=taxonomic-tab-actions]').click()
                cy.get('[data-attr=prop-filter-actions-7]').click({ force: true })
                cy.wait('@getLifecycleInsight').then(({ request }) => {
                    expect(request.query.actions).to.be.oneOf([
                        '[{"id":"1","name":"Hogflix homepage view","type":"actions","order":0,"math":"total"}]',
                        '[{"type":"actions","id":"1","name":"Hogflix homepage view"}]', // data exploration
                    ])
                })

                // rename action
                cy.get('[data-attr=show-prop-rename-0]').click()
                cy.get('[data-attr=filter-rename-modal]').within(() => {
                    cy.get('input').type('Homepage view{enter}')
                })
                cy.wait('@getLifecycleInsight').then(({ request }) => {
                    expect(request.query.actions).to.be.oneOf([
                        '[{"id":"1","name":"Hogflix homepage view","type":"actions","order":0,"math":"total","custom_name":"Homepage view"}]',
                        '[{"type":"actions","id":"1","name":"Hogflix homepage view","custom_name":"Homepage view"}]', // data exploration
                    ])
                })

                //  add browser filter
                cy.get('[data-attr=show-prop-filter-0]').click()
                cy.get('[data-attr="property-select-toggle-0"]').click()
                cy.get('[data-attr="prop-filter-event_properties-0"]').click()

                // select safari
                cy.get('[data-attr=prop-val]').click()
                cy.get('[data-attr=prop-val-0]').click({ force: true })

                cy.wait('@getLifecycleInsight').then(({ request }) => {
                    expect(request.query.actions).to.be.oneOf([
                        '[{"id":"1","name":"Hogflix homepage view","type":"actions","order":0,"math":"total","custom_name":"Homepage view","properties":[{"key":"$browser","value":["Safari"],"operator":"exact","type":"event"}]}]',
                        '[{"type":"actions","id":"1","name":"Hogflix homepage view","custom_name":"Homepage view","properties":[{"key":"$browser","value":["Safari"],"operator":"exact","type":"event"}]}]', // data exploration
                    ])
                })
            })

            it('handles test account filter change', () => {
                cy.wait('@getLifecycleInsight')

                // toggle test users
                cy.get('label').contains('Filter out internal and test users').click()

                cy.wait('@getLifecycleInsight').then(({ request, response }) => {
                    expect(request.query.filter_test_accounts).to.eq('true')

                    // TODO: test data should include test users
                    expect(response.body.result[0]).to.include({ status: 'new', count: 2 })
                    expect(response.body.result[1]).to.include({ status: 'dormant', count: -99 })
                    expect(response.body.result[2]).to.include({ status: 'resurrecting', count: 92 })
                    expect(response.body.result[3]).to.include({ status: 'returning', count: 0 })
                })
            })

            it.skip('handles lifecycle toggle', () => {
                cy.wait('@getLifecycleInsight')

                // toggle dormant
                cy.get('label').contains('Dormant').click()

                // TODO: can't test this, because as changes only reflected in shadow dom / canvas
            })

            it('handles date range change', () => {
                cy.wait('@getLifecycleInsight')

                // change date range
                cy.get('[data-attr=date-filter]').click()
                cy.contains('Last 30 days').click()

                cy.wait('@getLifecycleInsight').then(({ request, response }) => {
                    expect(request.query.date_from).to.eq('-30d')
                    expect(request.query.date_to).to.eq(undefined)

                    expect(response.body.result[0]).to.include({ status: 'new', count: 2 })
                    expect(response.body.result[1]).to.include({ status: 'dormant', count: -155 })
                    expect(response.body.result[2]).to.include({ status: 'resurrecting', count: 155 })
                    expect(response.body.result[3]).to.include({ status: 'returning', count: 0 })
                })
            })

            it('handles interval change', () => {
                cy.wait('@getLifecycleInsight')

                // change interval
                cy.get('[data-attr=interval-filter]').click()
                cy.contains('Week').click()

                cy.wait('@getLifecycleInsight').then(({ request, response }) => {
                    expect(request.query.interval).to.eq('week')

                    expect(response.body.result[0]).to.include({ status: 'new', count: 14 })
                    expect(response.body.result[1]).to.include({ status: 'dormant', count: -134 })
                    expect(response.body.result[2]).to.include({ status: 'resurrecting', count: 87 })
                    expect(response.body.result[3]).to.include({ status: 'returning', count: 0 })
                })
            })

            it('handles refresh', () => {
                cy.wait('@getLifecycleInsight')
                // TODO: add new events to test data

                // refresh
                cy.get('button').contains('Refresh').click()

                cy.wait('@getLifecycleInsight').then(({ request }) => {
                    expect(request.query.refresh).to.eq('true')
                })
            })
        })
    })
})
