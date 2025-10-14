import { ReplayPlugin } from '@posthog/rrweb'
import { EventType, IncrementalSource, eventWithTime } from '@posthog/rrweb-types'

export const AudioMuteReplayerPlugin = (isMuted: boolean): ReplayPlugin => {
    const applyMuteToElement = (element: HTMLElement): void => {
        if (element.tagName === 'AUDIO' || element.tagName === 'VIDEO') {
            ;(element as HTMLMediaElement).muted = isMuted
        }

        // Also check for nested media elements
        const mediaElements = element.querySelectorAll('audio, video')
        mediaElements.forEach((media) => {
            ;(media as HTMLMediaElement).muted = isMuted
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

        handler: (e: eventWithTime, _isSync: boolean, { replayer }) => {
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
