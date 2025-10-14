import { ReplayPlugin, Replayer } from '@posthog/rrweb'
import { EventType, IncrementalSource, eventWithTime } from '@posthog/rrweb-types'

export const AudioMuteReplayerPlugin = (isMuted: boolean): ReplayPlugin => {
    const applyMuteToMediaElement = (element: HTMLElement): void => {
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
