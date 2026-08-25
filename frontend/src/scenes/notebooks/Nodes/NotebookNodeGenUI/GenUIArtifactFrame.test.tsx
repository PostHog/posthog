import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { GenUIArtifactFrame } from './GenUIArtifactFrame'

class TestMessagePort {
    close = jest.fn()
    postMessage = jest.fn()
    addEventListener = jest.fn()
    start = jest.fn()
}

class TestMessageChannel {
    port1 = new TestMessagePort()
    port2 = new TestMessagePort()
}

describe('GenUIArtifactFrame', () => {
    const OriginalMessageChannel = window.MessageChannel
    let messageChannel: TestMessageChannel

    beforeEach(() => {
        initKeaTests()
        jest.useFakeTimers()
        window.MessageChannel = jest.fn(() => {
            messageChannel = new TestMessageChannel()
            return messageChannel
        }) as unknown as typeof MessageChannel
    })

    afterEach(() => {
        cleanup()
        jest.runOnlyPendingTimers()
        jest.useRealTimers()
        window.MessageChannel = OriginalMessageChannel
    })

    it('closes the artifact MessagePort when the frame unmounts', () => {
        const { unmount } = render(
            <GenUIArtifactFrame
                artifactUrl="https://example.com/globe.html"
                allowedFrames={[]}
                onReadFrame={jest.fn()}
            />
        )
        const iframe = screen.getByTitle('Generated visualization')
        expect(iframe).toHaveAttribute('src', 'https://example.com/globe.html#theme=light')
        expect(iframe).not.toHaveAttribute('srcdoc')
        fireEvent.load(iframe)

        unmount()

        expect(messageChannel.port1.close).toHaveBeenCalled()
    })

    it('reports an unavailable artifact when it does not render in time', () => {
        const onArtifactUnavailable = jest.fn()
        render(
            <GenUIArtifactFrame
                artifactUrl="https://example.com/globe.html"
                allowedFrames={[]}
                onReadFrame={jest.fn()}
                onArtifactUnavailable={onArtifactUnavailable}
            />
        )
        fireEvent.load(screen.getByTitle('Generated visualization'))

        act(() => jest.advanceTimersByTime(20_000))

        expect(onArtifactUnavailable).toHaveBeenCalledTimes(1)
    })
})
