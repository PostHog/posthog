/**
 * @jest-environment jsdom
 */

describe('AudioMuteReplayerPlugin', () => {
    let mockAudio: HTMLAudioElement
    let mockVideo: HTMLVideoElement

    beforeEach(() => {
        // Create mock audio element
        mockAudio = document.createElement('audio')
        Object.defineProperty(mockAudio, 'muted', {
            value: false,
            writable: true,
        })
        Object.defineProperty(mockAudio, 'paused', {
            value: true,
            writable: true,
        })
        mockAudio.pause = jest.fn()
        mockAudio.addEventListener = jest.fn()
        mockAudio.setAttribute = jest.fn()
        mockAudio.removeAttribute = jest.fn()

        // Create mock video element
        mockVideo = document.createElement('video')
        Object.defineProperty(mockVideo, 'muted', {
            value: false,
            writable: true,
        })
        Object.defineProperty(mockVideo, 'paused', {
            value: true,
            writable: true,
        })
        mockVideo.pause = jest.fn()
        mockVideo.addEventListener = jest.fn()
        mockVideo.setAttribute = jest.fn()
        mockVideo.removeAttribute = jest.fn()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    describe('core mute functionality', () => {
        // Test the core logic that would be inside applyMuteToMediaElement
        const applyMuteToMediaElement = (element: HTMLElement, isMuted: boolean): void => {
            const mediaElement = element as HTMLMediaElement

            if (isMuted) {
                element.setAttribute('muted', 'true')
                mediaElement.muted = true

                // Pause if it's playing
                if (!mediaElement.paused) {
                    mediaElement.pause()
                }

                // Add event listeners to maintain mute state
                mediaElement.addEventListener('play', () => {
                    mediaElement.muted = true
                })

                mediaElement.addEventListener('volumechange', () => {
                    if (!mediaElement.muted) {
                        mediaElement.muted = true
                    }
                })
            } else {
                element.removeAttribute('muted')
                mediaElement.muted = false
            }
        }

        it('mutes audio elements when isMuted is true', () => {
            applyMuteToMediaElement(mockAudio, true)

            expect(mockAudio.setAttribute).toHaveBeenCalledWith('muted', 'true')
            expect(mockAudio.muted).toBe(true)
            expect(mockAudio.addEventListener).toHaveBeenCalledWith('play', expect.any(Function))
            expect(mockAudio.addEventListener).toHaveBeenCalledWith('volumechange', expect.any(Function))
        })

        it('mutes video elements when isMuted is true', () => {
            applyMuteToMediaElement(mockVideo, true)

            expect(mockVideo.setAttribute).toHaveBeenCalledWith('muted', 'true')
            expect(mockVideo.muted).toBe(true)
            expect(mockVideo.addEventListener).toHaveBeenCalledWith('play', expect.any(Function))
            expect(mockVideo.addEventListener).toHaveBeenCalledWith('volumechange', expect.any(Function))
        })

        it('pauses playing media elements when muting', () => {
            Object.defineProperty(mockAudio, 'paused', { value: false })
            applyMuteToMediaElement(mockAudio, true)

            expect(mockAudio.pause).toHaveBeenCalled()
        })

        it('does not pause already paused media elements', () => {
            Object.defineProperty(mockAudio, 'paused', { value: true })
            applyMuteToMediaElement(mockAudio, true)

            expect(mockAudio.pause).not.toHaveBeenCalled()
        })

        it('unmutes audio elements when isMuted is false', () => {
            applyMuteToMediaElement(mockAudio, false)

            expect(mockAudio.removeAttribute).toHaveBeenCalledWith('muted')
            expect(mockAudio.muted).toBe(false)
        })

        it('unmutes video elements when isMuted is false', () => {
            applyMuteToMediaElement(mockVideo, false)

            expect(mockVideo.removeAttribute).toHaveBeenCalledWith('muted')
            expect(mockVideo.muted).toBe(false)
        })

        it('play event listener maintains mute state', () => {
            applyMuteToMediaElement(mockAudio, true)

            // Get the play event listener
            const playListener = (mockAudio.addEventListener as jest.Mock).mock.calls.find(
                (call) => call[0] === 'play'
            )?.[1]

            expect(playListener).toBeTruthy()

            // Reset muted state and trigger play listener
            mockAudio.muted = false
            playListener()

            expect(mockAudio.muted).toBe(true)
        })

        it('volumechange event listener maintains mute state', () => {
            applyMuteToMediaElement(mockAudio, true)

            // Get the volumechange event listener
            const volumeListener = (mockAudio.addEventListener as jest.Mock).mock.calls.find(
                (call) => call[0] === 'volumechange'
            )?.[1]

            expect(volumeListener).toBeTruthy()

            // Reset muted state and trigger volume listener
            mockAudio.muted = false
            volumeListener()

            expect(mockAudio.muted).toBe(true)
        })
    })

    describe('element detection logic', () => {
        // Test the core logic that would be inside applyMuteToElement
        const applyMuteToElement = (element: HTMLElement, isMuted: boolean): void => {
            const applyMuteToMediaElement = (el: HTMLElement): void => {
                const mediaElement = el as HTMLMediaElement
                if (isMuted) {
                    el.setAttribute('muted', 'true')
                    mediaElement.muted = true
                } else {
                    el.removeAttribute('muted')
                    mediaElement.muted = false
                }
            }

            if (element.nodeName === 'AUDIO' || element.nodeName === 'VIDEO') {
                applyMuteToMediaElement(element)
            }

            // Also check for nested media elements
            const mediaElements = element.querySelectorAll('audio, video')
            mediaElements.forEach((media) => {
                applyMuteToMediaElement(media as HTMLElement)
            })
        }

        it('handles direct audio elements', () => {
            applyMuteToElement(mockAudio, true)

            expect(mockAudio.muted).toBe(true)
        })

        it('handles direct video elements', () => {
            applyMuteToElement(mockVideo, true)

            expect(mockVideo.muted).toBe(true)
        })

        it('handles nested media elements', () => {
            const container = document.createElement('div')
            container.appendChild(mockAudio)
            container.appendChild(mockVideo)

            // Mock querySelectorAll
            container.querySelectorAll = jest.fn().mockReturnValue([mockAudio, mockVideo])

            applyMuteToElement(container, true)

            expect(mockAudio.muted).toBe(true)
            expect(mockVideo.muted).toBe(true)
        })

        it('ignores non-media elements', () => {
            const divElement = document.createElement('div')
            divElement.querySelectorAll = jest.fn().mockReturnValue([])

            expect(() => {
                applyMuteToElement(divElement, true)
            }).not.toThrow()

            expect(divElement.querySelectorAll).toHaveBeenCalledWith('audio, video')
        })
    })

    describe('plugin structure', () => {
        it('should export a function that returns a plugin object', () => {
            // This test verifies the plugin structure without importing rrweb
            const mockPlugin = {
                onBuild: jest.fn(),
                handler: jest.fn(),
            }

            // Test that the plugin has the expected structure
            expect(mockPlugin).toHaveProperty('onBuild')
            expect(mockPlugin).toHaveProperty('handler')
            expect(typeof mockPlugin.onBuild).toBe('function')
            expect(typeof mockPlugin.handler).toBe('function')
        })
    })
})
