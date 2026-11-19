import { act, cleanup, render } from '@testing-library/react'
import { StrictMode, Suspense } from 'react'

import { SceneContentFallback } from 'scenes/SceneContentFallback'
import { useSceneContentReady } from 'scenes/useSceneContentReady'

import { StorySceneReady } from './StorySceneReady'

function DataContent({ ready }: { ready: boolean }): JSX.Element {
    useSceneContentReady(ready)
    return <div>{ready ? 'Loaded data' : 'Pending data'}</div>
}

function LazyContent({ ready, pending }: { ready: boolean; pending: Promise<void> }): JSX.Element {
    if (!ready) {
        throw pending
    }
    return <div>Loaded content</div>
}

afterEach(cleanup)

it.each(['data', 'suspense'] as const)('waits for %s and cannot reuse readiness across story mounts', async (kind) => {
    let resolve: () => void = () => {}
    const pending = new Promise<void>((done) => {
        resolve = done
    })
    const story = (id: string, ready: boolean): JSX.Element => (
        <StrictMode>
            <StorySceneReady key={id} storyId={id}>
                {kind === 'data' ? (
                    <DataContent ready={ready} />
                ) : (
                    <Suspense
                        fallback={
                            <SceneContentFallback>
                                <div>Loading</div>
                            </SceneContentFallback>
                        }
                    >
                        <LazyContent ready={ready} pending={pending} />
                    </Suspense>
                )}
            </StorySceneReady>
        </StrictMode>
    )
    const { rerender, unmount } = render(story('first', false))
    await act(async () => {})
    expect(window.__STORYBOOK_SCENE_READINESS__?.getReadyVersion()).toBeNull()

    await act(async () => {
        resolve()
        rerender(story('first', true))
    })
    const first = window.__STORYBOOK_SCENE_READINESS__!
    expect(first.storyId).toBe('first')
    expect(first.getReadyVersion()).not.toBeNull()

    if (kind === 'data') {
        rerender(story('first', false))
        expect(first.getReadyVersion()).toBeNull()
        await act(async () => rerender(story('first', true)))
        expect(first.getReadyVersion()).not.toBeNull()
    }

    await act(async () => rerender(story('second', true)))
    expect(first.getReadyVersion()).toBeNull()
    expect(window.__STORYBOOK_SCENE_READINESS__?.storyId).toBe('second')
    expect(window.__STORYBOOK_SCENE_READINESS__?.instanceId).not.toBe(first.instanceId)
    expect(window.__STORYBOOK_SCENE_READINESS__?.getReadyVersion()).not.toBeNull()
    unmount()
    expect(window.__STORYBOOK_SCENE_READINESS__).toBeUndefined()
})
