import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { CanvasAppWidget } from './CanvasAppWidget'

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
