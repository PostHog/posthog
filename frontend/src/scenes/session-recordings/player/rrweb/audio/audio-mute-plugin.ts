import { ReplayPlugin, Replayer } from '@posthog/rrweb'
import { EventType, IncrementalSource, eventWithTime } from '@posthog/rrweb-types'

export const AudioMuteReplayerPlugin = (isMuted: boolean): ReplayPlugin => {
    const applyMuteToMediaElement = (element: HTMLElement): void => {
        const mediaElement = element as HTMLMediaElement

        // Clean up any existing listeners first
        if ((mediaElement as any).__muteListenersCleanup) {
            ;(mediaElement as any).__muteListenersCleanup()
        }

        if (isMuted) {
            element.setAttribute('muted', 'true')
            mediaElement.muted = true

            // Pause if it's playing
            if (!mediaElement.paused) {
                mediaElement.pause()
            }

            // Store listeners to clean them up later
            const playListener = (): void => {
                mediaElement.muted = true
            }
            const volumeChangeListener = (): void => {
                if (!mediaElement.muted) {
                    mediaElement.muted = true
                }
            }

            mediaElement.addEventListener('play', playListener)
            mediaElement.addEventListener('volumechange', volumeChangeListener)

            // Store cleanup function on the element for later removal
            ;(mediaElement as any).__muteListenersCleanup = (): void => {
                mediaElement.removeEventListener('play', playListener)
                mediaElement.removeEventListener('volumechange', volumeChangeListener)
            }
        } else {
            element.removeAttribute('muted')
            mediaElement.muted = false

            // Clean up listeners when unmuting since they're no longer needed
            if ((mediaElement as any).__muteListenersCleanup) {
                ;(mediaElement as any).__muteListenersCleanup()
                delete (mediaElement as any).__muteListenersCleanup
            }
        }
    }

    const applyMuteToElement = (element: HTMLElement): void => {
        if (element.nodeName === 'AUDIO' || element.nodeName === 'VIDEO') {
            applyMuteToMediaElement(element)
        }

        // Also check for nested media elements
        const mediaElements = element.querySelectorAll('audio, video')
        mediaElements.forEach((media) => {
            applyMuteToMediaElement(media as HTMLElement)
        })
    }

    return {
        onBuild: (node) => {
            if (!node || node.nodeType !== Node.ELEMENT_NODE) {
                return
            }

            const element = node as HTMLElement
            applyMuteToElement(element)
        },

        handler: (e: eventWithTime, _isSync: boolean, { replayer }: { replayer: Replayer }) => {
            // Handle DOM mutations that might add new media elements
            if (e.type === EventType.IncrementalSnapshot && e.data.source === IncrementalSource.Mutation) {
                // Apply mute state to any newly added nodes
                if (e.data.adds) {
                    e.data.adds.forEach((addedNode: any) => {
                        if (addedNode.node && addedNode.node.type === 1) {
                            // Element node
                            // Get the actual DOM node from the replayer's mirror
                            const domNode = replayer.getMirror().getNode(addedNode.node.id)
                            if (domNode && domNode.nodeType === Node.ELEMENT_NODE) {
                                applyMuteToElement(domNode as HTMLElement)
                            }
                        }
                    })
                }
            }
        },
    } as ReplayPlugin
}
