import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { canvasHostLogic, handleCanvasDataRequest } from 'products/canvas/frontend/host/canvasHostLogic'

import { CanvasAppWidget } from './CanvasAppWidget'
import { canvasAppWidgetLogic } from './canvasAppWidgetLogic'

describe('CanvasAppWidget', () => {
    afterEach(() => {
        cleanup()
    })

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/canvases/': () => [200, { results: [], count: 0 }],
            },
        })
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM })
        teamLogic.mount()
    })

    const noCanvasSelected = { canvas: null, needsConfiguration: true }

    it.each(['canvas', 'tool'] as const)(
        'identifies each requesting tile from the canvas API in %s consent',
        async (reason) => {
            const canvasIds = ['11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222']
            useMocks({
                get: Object.fromEntries(
                    canvasIds.map((id) => [
                        `/api/projects/:team_id/canvases/${id}/view/`,
                        () => [
                            200,
                            {
                                canvas: { id, name: 'Release overview', channel: 'space-1' },
                                published_build: {
                                    id: `build-${id}`,
                                    source_version_id: 'version-1',
                                    artifact_url: 'https://artifacts.example.com/canvas/index.html',
                                },
                            },
                        ],
                    ])
                ),
                post: {
                    '/api/projects/:team_id/canvases/:id/connectors/call/': () => [
                        200,
                        { status: 'needs_approval', approval_token: 'example-approval-token' },
                    ],
                },
            })
            render(
                <>
                    {canvasIds.map((id, index) => (
                        <CanvasAppWidget
                            key={id}
                            tileId={index + 1}
                            config={{ canvasId: id }}
                            loading={false}
                            result={{ canvas: { id, name: 'Outdated tile title', publishedBuildId: `build-${id}` } }}
                        />
                    ))}
                </>
            )

            for (const [index, canvasId] of canvasIds.entries()) {
                const tile = canvasAppWidgetLogic({ tileId: index + 1, canvasId })
                await waitFor(() => expect(tile.values.renderState).toBe('built'))
                const host = canvasHostLogic.findMounted(tile.values.hostProps)!
                let response: Promise<unknown>
                act(() => {
                    response = handleCanvasDataRequest(host, 'connectorCall', {
                        provider: 'github',
                        tool: 'list_pull_requests',
                        arguments: {},
                        canvasId: 'iframe-canvas',
                        canvasName: 'Iframe title',
                    }).catch((error) => error)
                })
                if (reason === 'tool') {
                    fireEvent.click(await screen.findByText('Allow access'))
                    await screen.findByText('Allow once')
                }

                const identityLink = await screen.findByText(canvasId)
                const dialog = within(identityLink.closest('[role="dialog"]') as HTMLElement)
                expect(dialog.getByText('Release overview')).toBeInTheDocument()
                expect(dialog.queryByText('Outdated tile title')).not.toBeInTheDocument()
                expect(dialog.queryByText('Iframe title')).not.toBeInTheDocument()
                expect(dialog.queryByText(canvasIds[1 - index])).not.toBeInTheDocument()
                expect(identityLink).toHaveAttribute('href', `/project/${MOCK_DEFAULT_TEAM.id}/canvases/${canvasId}`)
                expect(identityLink).toHaveAttribute('target', '_blank')
                fireEvent.click(dialog.getByText('Cancel'))
                await expect(response!).resolves.toEqual(expect.any(Error))
            }
        }
    )

    it('lets an editor pick a canvas inline when none is selected', () => {
        const { container } = render(
            <CanvasAppWidget
                tileId={1}
                config={{}}
                loading={false}
                result={noCanvasSelected}
                onUpdateConfig={jest.fn()}
            />
        )

        expect(screen.getByText('No canvas selected')).toBeInTheDocument()
        expect(container.querySelector('[data-attr="canvas-app-widget-empty-state-select"]')).toBeInTheDocument()
    })

    it('points to the MCP server instead of a create button when the viewer has none to pick', () => {
        render(
            <CanvasAppWidget
                tileId={1}
                config={{}}
                loading={false}
                result={{ ...noCanvasSelected, hasCanvases: false }}
                onUpdateConfig={jest.fn()}
            />
        )

        expect(screen.getByText('No canvases yet')).toBeInTheDocument()
        expect(screen.getByText(/PostHog MCP server/)).toBeInTheDocument()
        expect(screen.queryByText('New canvas')).not.toBeInTheDocument()
        expect(screen.queryByText('No canvas selected')).not.toBeInTheDocument()
    })

    it('does not expose the inline picker on a read-only (shared) tile', () => {
        const { container } = render(
            <CanvasAppWidget tileId={1} config={{}} loading={false} result={noCanvasSelected} />
        )

        expect(screen.getByText('No canvas has been selected for this tile yet.')).toBeInTheDocument()
        expect(container.querySelector('[data-attr="canvas-app-widget-empty-state-select"]')).not.toBeInTheDocument()
    })

    it('tells the viewer when the canvas is not visible to them', () => {
        render(
            <CanvasAppWidget
                tileId={1}
                config={{ canvasId: '00000000-0000-0000-0000-000000000000' }}
                loading={false}
                result={{ canvas: null, canvasNotFound: true }}
            />
        )

        expect(screen.getByText('Canvas not available')).toBeInTheDocument()
    })
})
