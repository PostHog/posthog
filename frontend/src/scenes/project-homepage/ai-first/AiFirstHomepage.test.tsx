import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import { ReactNode, Suspense } from 'react'

import { SceneRenderedMarkContext } from 'scenes/SceneContentFallback'

import { AiFirstHomepage } from './AiFirstHomepage'

let mockContentReady: boolean
let mockPendingContent: Promise<void>
let releaseContent: () => void
let pendingContentHolds: number

jest.mock('kea', () => ({
    BindLogic: ({ children }: { children: ReactNode }) => children,
    useValues: () => ({
        mode: 'ai',
        animationPhase: 'content',
        query: '',
        threadStarted: true,
        conversationId: 'example-conversation',
    }),
}))

jest.mock('./aiFirstHomepageLogic', () => ({ aiFirstHomepageLogic: {} }))
jest.mock('scenes/max/maxLogic', () => ({ maxLogic: () => ({}) }))
jest.mock('lib/components/Search/Search', () => ({
    Search: { Root: ({ children }: { children: ReactNode }) => <div>{children}</div> },
}))
jest.mock('~/layout/scenes/components/SceneBreadcrumbs', () => ({ SceneBreadcrumbBackButton: () => null }))
jest.mock('./HomepageInput', () => ({ HomepageInput: () => <input data-attr="home-input" /> }))
jest.mock('scenes/max/components/AiFirstMaxInstance', () => ({
    ChatHeader: () => {
        if (!mockContentReady) {
            throw mockPendingContent
        }
        return <div data-attr="header" />
    },
}))
jest.mock('./HomepageThread', () => ({
    HomepageThread: () => <div data-attr="thread" />,
}))

describe('AiFirstHomepage', () => {
    beforeEach(() => {
        mockContentReady = false
        pendingContentHolds = 0
        mockPendingContent = new Promise<void>((resolve) => {
            releaseContent = resolve
        })
    })

    afterEach(cleanup)

    it('keeps the input visible while the header loads', async () => {
        render(
            <SceneRenderedMarkContext.Provider
                value={{
                    holdUntilContent: () => {
                        pendingContentHolds++
                        return () => {
                            pendingContentHolds--
                        }
                    },
                    sceneCommitted: jest.fn(),
                    sceneUncommitted: jest.fn(),
                }}
            >
                <Suspense fallback={<div data-attr="home-loading" />}>
                    <AiFirstHomepage />
                </Suspense>
            </SceneRenderedMarkContext.Provider>
        )

        expect(screen.getByTestId('home-input')).toBeVisible()
        expect(screen.queryByTestId('home-loading')).not.toBeInTheDocument()
        expect(screen.queryByTestId('header')).not.toBeInTheDocument()
        expect(pendingContentHolds).toBeGreaterThan(0)

        await act(async () => {
            mockContentReady = true
            releaseContent()
        })

        expect(await screen.findByTestId('header')).toBeVisible()
        expect(pendingContentHolds).toBe(0)
    })
})
