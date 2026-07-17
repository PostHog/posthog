import { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'

import {
    createInsightStory,
    insightSceneMswDecorator,
    insightSceneStoryParameters,
} from 'scenes/insights/__mocks__/createInsightScene'
import { InsightVizStory } from 'scenes/insights/__mocks__/createInsightVizStory'

import __userPaths from '~/mocks/fixtures/api/projects/team_id/insights/userPaths.json'

import { Paths } from './Paths'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/Paths',
    component: Paths,
    parameters: {
        layout: 'centered',
        mockDate: '2022-03-11',
        testOptions: {
            snapshotBrowsers: ['chromium'],
            // The Paths component removes data-stable from its canvas while (re)building the SVG
            // and re-adds it once settled, so this waits out the resize-observer churn.
            waitForSelector: ['[data-attr=path-node-card-button]', '[data-attr=paths-viz][data-stable]'],
        },
    },
}
export default meta

export const UserPaths: Story = {
    render: () => (
        <InsightVizStory insight={__userPaths as any} width={1000}>
            {/* Paths sizes its canvas from the container, so it needs explicit dimensions */}
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <div style={{ height: 576 }}>
                <Paths />
            </div>
        </InsightVizStory>
    ),
}

// The Paths component uses useResizeObserver to measure canvasWidth/canvasHeight, then destroys
// and recreates the SVG when they change (or when theme/data changes). Dimension updates are
// debounced to reduce recreations. The canvas div gets data-stable removed during recreation
// and re-added after, so waiting for [data-attr=paths-viz][data-stable] ensures the SVG has
// fully settled. We require 3 consecutive stable checks (600ms apart) for extra confidence.
const waitForPathsCanvasToStabilize: NonNullable<Story['play']> = async ({ canvasElement }) => {
    let lastWidth = 0
    let lastHeight = 0
    let lastSvgElement: Element | null = null
    let stableCount = 0
    await waitFor(
        () => {
            const canvas = canvasElement.querySelector('[data-attr=paths-viz][data-stable]')
            const svg = canvas ? canvas.querySelector('.Paths__canvas') : null
            const rect = svg ? svg.getBoundingClientRect() : null
            const currentWidth = rect ? rect.width : 0
            const currentHeight = rect ? rect.height : 0
            if (
                !canvas ||
                !svg ||
                currentWidth === 0 ||
                currentHeight === 0 ||
                currentWidth !== lastWidth ||
                currentHeight !== lastHeight ||
                svg !== lastSvgElement
            ) {
                lastWidth = currentWidth
                lastHeight = currentHeight
                lastSvgElement = svg
                stableCount = 0
                throw new Error('SVG not yet stable')
            }
            stableCount++
            if (stableCount < 3) {
                throw new Error('SVG not yet confirmed stable')
            }
        },
        { timeout: 8000, interval: 200 }
    )
}

// Full insight scene in edit mode — the paths editor
export const EditScene: Story = createInsightStory(__userPaths as any, 'edit')
EditScene.decorators = [insightSceneMswDecorator]
EditScene.parameters = {
    ...insightSceneStoryParameters,
    testOptions: {
        ...insightSceneStoryParameters.testOptions,
        waitForSelector: ['[data-attr=path-node-card-button]:nth-child(7)', '[data-attr=paths-viz][data-stable]'],
    },
}
EditScene.play = waitForPathsCanvasToStabilize
