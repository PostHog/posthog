/**
 * @jest-environment jsdom
 */
import { isMediaElementPlaying } from '../../utils/media-utils'
import { setupFeedbackAudioObserver } from './feedback-audio-observer'

describe('feedback audio observer', () => {
    let mockAudio: HTMLAudioElement
    let container: HTMLElement
    let observer: MutationObserver | null = null

    beforeEach(() => {
        container = document.createElement('div')
        document.body.appendChild(container)

        mockAudio = document.createElement('audio')
        mockAudio.setAttribute('data-posthog-recording', 'true')
        Object.defineProperty(mockAudio, 'paused', { value: true, writable: true })
        Object.defineProperty(mockAudio, 'ended', { value: false, writable: true })
        Object.defineProperty(mockAudio, 'currentTime', { value: 0, writable: true })
        Object.defineProperty(mockAudio, 'readyState', { value: 4, writable: true })
        mockAudio.play = jest.fn().mockResolvedValue(undefined)
    })

    afterEach(() => {
        observer?.disconnect()
        observer = null
        document.body.removeChild(container)
    })

    it('detects feedback audio elements and calls play when added directly to the DOM', (done) => {
        observer = setupFeedbackAudioObserver(container)
        container.appendChild(mockAudio)

        setTimeout(() => {
            expect(mockAudio.play).toHaveBeenCalled()
            done()
        }, 50)
    })

    it('detects feedback audio elements nested within added elements', (done) => {
        const wrapper = document.createElement('div')
        wrapper.appendChild(mockAudio)

        observer = setupFeedbackAudioObserver(container)
        container.appendChild(wrapper)

        setTimeout(() => {
            expect(mockAudio.play).toHaveBeenCalled()
            done()
        }, 50)
    })

    it('does not trigger play for regular audio elements without data-posthog-recording attribute', (done) => {
        const regularAudio = document.createElement('audio')
        regularAudio.play = jest.fn().mockResolvedValue(undefined)

        observer = setupFeedbackAudioObserver(container)
        container.appendChild(regularAudio)

        setTimeout(() => {
            expect(regularAudio.play).not.toHaveBeenCalled()
            done()
        }, 50)
    })

    it('does not trigger play for audio elements with data-posthog-recording set to false', (done) => {
        const otherAudio = document.createElement('audio')
        otherAudio.setAttribute('data-posthog-recording', 'false')
        otherAudio.play = jest.fn().mockResolvedValue(undefined)

        observer = setupFeedbackAudioObserver(container)
        container.appendChild(otherAudio)

        setTimeout(() => {
            expect(otherAudio.play).not.toHaveBeenCalled()
            done()
        }, 50)
    })

    it('does not call play on feedback audio elements that are already playing', (done) => {
        Object.defineProperty(mockAudio, 'paused', { value: false })
        Object.defineProperty(mockAudio, 'currentTime', { value: 1 })

        observer = setupFeedbackAudioObserver(container)
        container.appendChild(mockAudio)

        setTimeout(() => {
            expect(mockAudio.play).not.toHaveBeenCalled()
            done()
        }, 50)
    })

    it('handles multiple feedback audio elements in a single mutation', (done) => {
        const audioElements: HTMLAudioElement[] = []
        for (let i = 0; i < 3; i++) {
            const audio = document.createElement('audio')
            audio.setAttribute('data-posthog-recording', 'true')
            Object.defineProperty(audio, 'paused', { value: true })
            Object.defineProperty(audio, 'currentTime', { value: 0 })
            Object.defineProperty(audio, 'readyState', { value: 4 })
            audio.play = jest.fn().mockResolvedValue(undefined)
            audioElements.push(audio)
        }

        const wrapper = document.createElement('div')
        audioElements.forEach((audio) => wrapper.appendChild(audio))

        observer = setupFeedbackAudioObserver(container)
        container.appendChild(wrapper)

        setTimeout(() => {
            audioElements.forEach((audio) => {
                expect(audio.play).toHaveBeenCalled()
            })
            done()
        }, 50)
    })

    it('continues observing after detecting elements', (done) => {
        observer = setupFeedbackAudioObserver(container)

        const audio1 = document.createElement('audio')
        audio1.setAttribute('data-posthog-recording', 'true')
        Object.defineProperty(audio1, 'paused', { value: true })
        Object.defineProperty(audio1, 'currentTime', { value: 0 })
        Object.defineProperty(audio1, 'readyState', { value: 4 })
        audio1.play = jest.fn().mockResolvedValue(undefined)
        container.appendChild(audio1)

        setTimeout(() => {
            expect(audio1.play).toHaveBeenCalled()

            const audio2 = document.createElement('audio')
            audio2.setAttribute('data-posthog-recording', 'true')
            Object.defineProperty(audio2, 'paused', { value: true })
            Object.defineProperty(audio2, 'currentTime', { value: 0 })
            Object.defineProperty(audio2, 'readyState', { value: 4 })
            audio2.play = jest.fn().mockResolvedValue(undefined)
            container.appendChild(audio2)

            setTimeout(() => {
                expect(audio2.play).toHaveBeenCalled()
                done()
            }, 50)
        }, 50)
    })

    it('returns a MutationObserver that can be disconnected', () => {
        observer = setupFeedbackAudioObserver(container)

        expect(observer).toBeInstanceOf(MutationObserver)
        expect(() => observer?.disconnect()).not.toThrow()
    })
})

describe('isMediaElementPlaying', () => {
    it.each([
        { currentTime: 0, paused: true, ended: false, readyState: 4, expected: false },
        { currentTime: 1, paused: true, ended: false, readyState: 4, expected: false },
        { currentTime: 1, paused: false, ended: false, readyState: 4, expected: true },
        { currentTime: 1, paused: false, ended: true, readyState: 4, expected: false },
        { currentTime: 1, paused: false, ended: false, readyState: 2, expected: false },
        { currentTime: 1, paused: false, ended: false, readyState: 3, expected: true },
        { currentTime: 0, paused: false, ended: false, readyState: 4, expected: false },
    ])(
        'returns $expected when currentTime=$currentTime, paused=$paused, ended=$ended, readyState=$readyState',
        ({ currentTime, paused, ended, readyState, expected }) => {
            const audio = document.createElement('audio')
            Object.defineProperty(audio, 'currentTime', { value: currentTime })
            Object.defineProperty(audio, 'paused', { value: paused })
            Object.defineProperty(audio, 'ended', { value: ended })
            Object.defineProperty(audio, 'readyState', { value: readyState })

            expect(isMediaElementPlaying(audio)).toBe(expected)
        }
    )
})
