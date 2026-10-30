import { combineUrl, router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { DataModelingEdge, DataModelingNode } from '~/types'

import { lineageDataLogic } from './lineageDataLogic'
import { modelsLineageLogic } from './modelsLineageLogic'

const NODES: DataModelingNode[] = [
    { id: '1', name: 'website_leads', type: 'table' },
    { id: '2', name: 'website_leads_daily', type: 'view' },
    { id: '3', name: 'app_onboarding_leads', type: 'view' },
    { id: '4', name: 'customers', type: 'view' },
] as DataModelingNode[]

// customers feeds website_leads, so an upstream selector keeps a cone of two nodes rather than one.
const EDGES: DataModelingEdge[] = [{ id: 'e1', source_id: '4', target_id: '1' }] as DataModelingEdge[]

describe('modelsLineageLogic', () => {
    let logic: ReturnType<typeof modelsLineageLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/data_modeling_nodes/': () => [200, { results: NODES, next: null }],
                '/api/environments/:team_id/data_modeling_edges/': () => [200, { results: EDGES, next: null }],
            },
        })
        initKeaTests()
        jest.mocked(posthog.capture).mockClear()
        logic = modelsLineageLogic()
        logic.mount()
        await expectLogic(lineageDataLogic).toDispatchActions(['loadNodesSuccess', 'loadEdgesSuccess'])
    })

    afterEach(() => {
        logic.unmount()
    })

    it.each([false, true])('opens the selected lineage from a URL with a stable ID: %s', async (useNodeId) => {
        const selectedNode = { ...NODES[0], id: 'selected-view' }
        const baseNodes = [selectedNode, ...NODES.slice(1)]
        const nodes = useNodeId
            ? [{ ...NODES[0], id: 'namesake-metric', type: 'metric' as const }, ...baseNodes]
            : baseNodes
        const edges = EDGES.map((edge) => ({ ...edge, target_id: selectedNode.id }))
        lineageDataLogic.actions.loadNodesSuccess(nodes)
        lineageDataLogic.actions.loadEdgesSuccess(edges)
        logic.actions.setTypeFilter(['view'])

        await expectLogic(logic, () => {
            router.actions.push(
                combineUrl(urls.models('lineage'), {
                    search: '+website_leads+',
                    ...(useNodeId ? { node_id: selectedNode.id } : {}),
                }).url
            )
        }).toMatchValues({
            searchTerm: '+website_leads+',
            debouncedSearchTerm: '+website_leads+',
            visibleNodes: [selectedNode, NODES[3]],
            visibleEdges: edges,
            lineageSearchAnchor: selectedNode,
        })

        await expectLogic(logic, () => {
            logic.actions.setSearchTerm('+customers+')
            logic.actions.setDebouncedSearchTerm('+customers+')
        }).toMatchValues({ searchAnchorNodeId: null, lineageSearchAnchor: NODES[3] })

        await expectLogic(logic, () => {
            router.actions.push(urls.models('lineage'))
        }).toMatchValues({
            searchTerm: '',
            visibleNodes: nodes,
        })
    })

    it('ranks plain search results without moving the graph', async () => {
        const position = { x: 120, y: 80 }
        logic.actions.nodeDragStopped('1', position)

        await expectLogic(logic, () => {
            logic.actions.setSearchTerm('leads')
            logic.actions.setDebouncedSearchTerm('leads')
        }).toMatchValues({
            searchResults: [NODES[0], NODES[1], NODES[2]],
            showSearchResults: true,
            selectedSearchResult: NODES[0],
            highlightedNodeIds: new Set(['1', '2', '3']),
            focusNodeIds: null,
            searchFocusRequest: null,
            nodePositions: { '1': position },
        })
    })

    it('filters search results by type and resets an explicit selection', async () => {
        logic.actions.setSearchTerm('leads')
        logic.actions.setDebouncedSearchTerm('leads')
        logic.actions.focusSearchResult('1', 'keyboard')

        await expectLogic(logic, () => {
            logic.actions.setTypeFilter(['view'])
        }).toMatchValues({
            searchResults: [NODES[1], NODES[2]],
            selectedSearchResultId: null,
            selectedSearchResult: NODES[1],
            searchFocusRequest: null,
        })
    })

    it('changes and wraps the selected result without creating a focus request', async () => {
        logic.actions.setSearchTerm('leads')
        logic.actions.setDebouncedSearchTerm('leads')

        await expectLogic(logic, () => {
            logic.actions.moveSearchResult('previous', false)
        })
            .toFinishAllListeners()
            .toMatchValues({
                selectedSearchResultId: '3',
                selectedSearchResult: NODES[2],
                searchFocusRequest: null,
            })

        await expectLogic(logic, () => {
            logic.actions.moveSearchResult('next', false)
        })
            .toFinishAllListeners()
            .toMatchValues({
                selectedSearchResultId: '1',
                selectedSearchResult: NODES[0],
                searchFocusRequest: null,
            })
    })

    it('increments focus requests for selected results', async () => {
        logic.actions.setSearchTerm('leads')
        logic.actions.setDebouncedSearchTerm('leads')
        logic.actions.focusSearchResult('1', 'keyboard')

        await expectLogic(logic).toMatchValues({
            selectedSearchResultId: '1',
            searchFocusRequest: { nodeId: '1', requestId: 1 },
        })

        await expectLogic(logic, () => {
            logic.actions.focusSearchResult('2', 'click')
        }).toMatchValues({
            selectedSearchResultId: '2',
            searchFocusRequest: { nodeId: '2', requestId: 2 },
        })

        await expectLogic(logic, () => {
            logic.actions.selectSearchResult('3')
        }).toMatchValues({
            selectedSearchResultId: '3',
            searchFocusRequest: null,
        })
    })

    it('keeps filters cleared when a search debounce is pending', async () => {
        logic.actions.setSearchTerm('+website_leads')
        logic.actions.resetFilters()

        await expectLogic(logic).delay(300).toMatchValues({
            searchTerm: '',
            debouncedSearchTerm: '',
        })
    })

    it('shows an empty result panel for an unmatched plain search', async () => {
        await expectLogic(logic, () => {
            logic.actions.setSearchTerm('missing')
            logic.actions.setDebouncedSearchTerm('missing')
        }).toMatchValues({
            searchResults: [],
            showSearchResults: true,
            selectedSearchResult: null,
            focusNodeIds: null,
        })
    })

    it('lists a lineage selector by graph distance and keeps the full cone behavior', async () => {
        logic.actions.setSearchTerm('+website_leads')

        await expectLogic(logic).toMatchValues({
            searchResults: [],
            showSearchResults: false,
        })

        await expectLogic(logic, () => {
            logic.actions.setDebouncedSearchTerm('+website_leads')
        }).toMatchValues({
            searchResults: [NODES[0], NODES[3]],
            showSearchResults: true,
            lineageSearchAnchor: NODES[0],
            selectedSearchResult: NODES[0],
            highlightedNodeIds: new Set(),
            focusNodeIds: new Set(['1', '4']),
        })
    })

    it('hides the result panel while the edges it needs are still loading', async () => {
        logic.actions.setSearchTerm('+website_leads')
        logic.actions.setDebouncedSearchTerm('+website_leads')

        await expectLogic(logic).toMatchValues({ showSearchResults: true })

        lineageDataLogic.actions.loadEdges()

        expectLogic(logic).toMatchValues({
            edgesLoading: true,
            showSearchResults: false,
            searchResultAnnouncement: '',
        })
    })

    it('cycles through and focuses models in a lineage selector', async () => {
        logic.actions.setSearchTerm('+website_leads')
        logic.actions.setDebouncedSearchTerm('+website_leads')

        await expectLogic(logic, () => {
            logic.actions.moveSearchResult('next', true)
        })
            .toFinishAllListeners()
            .toMatchValues({
                selectedSearchResult: NODES[3],
                searchFocusRequest: { nodeId: '4', requestId: 1 },
            })
    })

    it.each(['type', 'lineage', 'clear'] as const)(
        'clears distant node positions when the %s filter changes the graph',
        async (filter) => {
            const position = { x: 100000, y: 100000 }

            if (filter === 'clear') {
                logic.actions.setSearchTerm('+website_leads+')
                logic.actions.setDebouncedSearchTerm('+website_leads+')
            }

            logic.actions.nodeDragStopped('1', position)
            expect(posthog.capture).toHaveBeenCalledWith('models lineage node moved', {
                node_type: 'table',
                is_filtered: filter === 'clear',
            })

            await expectLogic(logic, () => {
                if (filter === 'type') {
                    logic.actions.setTypeFilter(['view'])
                } else if (filter === 'lineage') {
                    logic.actions.setSearchTerm('+website_leads+')
                    logic.actions.setDebouncedSearchTerm('+website_leads+')
                } else {
                    logic.actions.resetFilters()
                }
            }).toMatchValues({ nodePositions: {} })
        }
    )
})
