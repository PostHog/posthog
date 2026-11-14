import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { NodeKind, VisualizationNode } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { dataVisualizationLogic } from '../../dataVisualizationLogic'
import { variableDataLogic } from './variableDataLogic'
import { variablesLogic } from './variablesLogic'

describe('variablesLogic', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/insight_variables/': {
                    results: [
                        {
                            id: 'region-id',
                            name: 'Region',
                            code_name: 'region',
                            type: 'String',
                            default_value: 'North',
                        },
                    ],
                },
            },
        })
        initKeaTests()
    })

    it('loads every definition page before treating missing selections as deleted', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/insight_variables/': ({ request }) => {
                    const page = new URL(request.url).searchParams.get('page')
                    return [
                        200,
                        page === '2'
                            ? {
                                  results: [
                                      {
                                          id: 'second-id',
                                          name: 'Second',
                                          code_name: 'second',
                                          type: 'String',
                                          default_value: '',
                                      },
                                  ],
                                  next: null,
                              }
                            : {
                                  results: [
                                      {
                                          id: 'first-id',
                                          name: 'First',
                                          code_name: 'first',
                                          type: 'String',
                                          default_value: '',
                                      },
                                  ],
                                  next: '/api/projects/2/insight_variables/?page=2',
                              },
                    ]
                },
            },
        })
        const logic = variableDataLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.variables.map((variable) => variable.id)).toEqual(['first-id', 'second-id'])
        logic.unmount()
    })

    it('keeps definitions when a delete request fails', async () => {
        useMocks({
            delete: { '/api/projects/:team_id/insight_variables/:id/': [500, { detail: 'Could not delete variable' }] },
        })
        const logic = variableDataLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.deleteVariable('region-id')).toFinishAllListeners()
        expect(logic.values.variables.map((variable) => variable.id)).toEqual(['region-id'])
        logic.unmount()
    })

    it.each([false, true])(
        'retains local values across saving and discarding edits with definitions loaded: %s',
        async (definitionsLoaded) => {
            let savedQuery: VisualizationNode = {
                kind: NodeKind.DataVisualizationNode,
                source: {
                    kind: NodeKind.HogQLQuery,
                    query: 'SELECT {variables.region}',
                    variables: {
                        'region-id': { variableId: 'region-id', code_name: 'region', value: 'South' },
                    },
                },
            }
            const parent = dataVisualizationLogic({
                dataNodeCollectionId: 'variables-test',
                key: 'variables-test',
                query: savedQuery,
                cachedResults: { columns: [], types: [], results: [] },
            })
            parent.mount()
            const props = {
                key: 'variables-test',
                readOnly: false,
                sourceQuery: savedQuery,
                setQuery: (query: VisualizationNode) => {
                    savedQuery = query
                },
            }
            const logic = variablesLogic(props)
            logic.mount()
            if (definitionsLoaded) {
                await expectLogic(variableDataLogic).toFinishAllListeners()
            }
            logic.actions.addVariable({ variableId: 'region-id', code_name: 'region', value: 'South' })
            logic.actions.setEditorQuery('SELECT 1')
            expect(savedQuery.source.variables).toEqual({})
            variablesLogic({ ...props, sourceQuery: savedQuery })
            await expectLogic(variableDataLogic).toFinishAllListeners()
            expect(logic.values.variablesNotInQuery).toEqual([expect.objectContaining({ value: 'South' })])
            logic.actions.setEditorQuery('SELECT {variables.region}')
            expect(savedQuery.source.variables).toEqual({
                'region-id': expect.objectContaining({ value: 'South' }),
            })
            const savedBeforeEdits = savedQuery
            logic.actions.setEditorQuery('SELECT 1')
            logic.actions.updateVariableValue('region-id', 'West', false)
            savedQuery = savedBeforeEdits
            variablesLogic({ ...props, sourceQuery: savedQuery })
            logic.actions.setEditorQuery('SELECT {variables.region}')
            expect(savedQuery.source.variables?.['region-id'].value).toBe('South')
            expect(logic.values.variablesUsedInQuery[0].value).toBe('South')
            logic.unmount()
            parent.unmount()
        }
    )
})
