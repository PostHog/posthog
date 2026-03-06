import { expectLogic } from 'kea-test-utils'

import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { DataVisualizationLogicProps, dataVisualizationLogic } from '../../dataVisualizationLogic'
import { variablesLogic } from './variablesLogic'

const testKey = 'test-variables-logic'
const dataNodeCollectionId = 'test-variables-collection'

const makeQuery = (withVariable: boolean): DataVisualizationNode => ({
    kind: NodeKind.DataVisualizationNode,
    source: {
        kind: NodeKind.HogQLQuery,
        query: withVariable
            ? 'SELECT event FROM events WHERE properties.$browser = {variables.browser}'
            : 'SELECT event FROM events',
        ...(withVariable
            ? {
                  variables: {
                      'var-browser-id': {
                          variableId: 'var-browser-id',
                          code_name: 'browser',
                          value: undefined,
                          isNull: false,
                      },
                  },
              }
            : {}),
    },
    display: ChartDisplayType.ActionsTable,
})

describe('variablesLogic', () => {
    let dvLogic: ReturnType<typeof dataVisualizationLogic.build>
    let varLogic: ReturnType<typeof variablesLogic.build>
    let mockSetQuery: jest.Mock

    beforeEach(() => {
        initKeaTests()
        mockSetQuery = jest.fn()
    })

    afterEach(() => {
        varLogic?.unmount()
        dvLogic?.unmount()
    })

    const mountLogics = (withVariable: boolean): void => {
        const query = makeQuery(withVariable)
        // dataVisualizationLogic must be mounted first — variablesLogic connects to it
        dvLogic = dataVisualizationLogic({
            key: testKey,
            query,
            dataNodeCollectionId,
        } as DataVisualizationLogicProps)
        dvLogic.mount()

        varLogic = variablesLogic({
            key: testKey,
            readOnly: false,
            sourceQuery: query,
            setQuery: mockSetQuery,
        })
        varLogic.mount()
    }

    describe('bug fix: removing a variable from SQL should update the query', () => {
        it('calls setQuery when _removeVariable is triggered', async () => {
            mountLogics(true)

            // Explicitly add the variable (simulates what propsChanged does when SQL has {variables.browser})
            varLogic.actions._addVariable({ variableId: 'var-browser-id', code_name: 'browser' })

            await expectLogic(varLogic).toMatchValues({
                internalSelectedVariables: expect.arrayContaining([
                    expect.objectContaining({ variableId: 'var-browser-id' }),
                ]),
            })

            // Reset mock so we only capture the _removeVariable-triggered call
            mockSetQuery.mockClear()

            // Simulate propsChanged detecting variable is no longer in SQL → calls _removeVariable
            varLogic.actions._removeVariable('var-browser-id')

            await expectLogic(varLogic).toMatchValues({
                internalSelectedVariables: [],
            })

            // THE KEY ASSERTION: setQuery must be called with empty variables.
            // Before the fix: _removeVariable had no listener → setQuery never called → stale filter on dashboard
            expect(mockSetQuery).toHaveBeenCalledWith(
                expect.objectContaining({
                    source: expect.objectContaining({
                        variables: {},
                    }),
                })
            )
        })

        it('does not crash when removing a variable that does not exist', async () => {
            mountLogics(false)

            // Should not throw even if the variable is not in internalSelectedVariables
            expect(() => varLogic.actions._removeVariable('var-browser-id')).not.toThrow()
        })

        it('keeps other variables when only one is removed', async () => {
            const queryWithTwoVars: DataVisualizationNode = {
                kind: NodeKind.DataVisualizationNode,
                source: {
                    kind: NodeKind.HogQLQuery,
                    query: 'SELECT * FROM events WHERE a = {variables.browser} AND b = {variables.platform}',
                    variables: {
                        'var-browser-id': {
                            variableId: 'var-browser-id',
                            code_name: 'browser',
                            value: undefined,
                            isNull: false,
                        },
                        'var-platform-id': {
                            variableId: 'var-platform-id',
                            code_name: 'platform',
                            value: undefined,
                            isNull: false,
                        },
                    },
                },
                display: ChartDisplayType.ActionsTable,
            }

            dvLogic = dataVisualizationLogic({
                key: testKey,
                query: queryWithTwoVars,
                dataNodeCollectionId,
            } as DataVisualizationLogicProps)
            dvLogic.mount()

            varLogic = variablesLogic({
                key: testKey,
                readOnly: false,
                sourceQuery: queryWithTwoVars,
                setQuery: mockSetQuery,
            })
            varLogic.mount()

            // Seed both variables
            varLogic.actions._addVariable({ variableId: 'var-browser-id', code_name: 'browser' })
            varLogic.actions._addVariable({ variableId: 'var-platform-id', code_name: 'platform' })
            mockSetQuery.mockClear()

            // Remove only browser — platform should remain in the query
            varLogic.actions._removeVariable('var-browser-id')

            expect(mockSetQuery).toHaveBeenCalledWith(
                expect.objectContaining({
                    source: expect.objectContaining({
                        variables: {
                            'var-platform-id': expect.objectContaining({ variableId: 'var-platform-id' }),
                        },
                    }),
                })
            )
        })
    })
})
