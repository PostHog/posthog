import { isMediaElementPlaying } from '../../utils/media-utils'

export const setupFeedbackAudioObserver = (targetElement: HTMLElement): MutationObserver => {
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            mutation.addedNodes.forEach((node) => {
                if (node.nodeType === 1) {
                    const element = node as Element

                    // Check if the added element is a feedback audio element
                    if (element.tagName === 'AUDIO' && element.getAttribute('data-posthog-recording') === 'true') {
                        const audio = element as HTMLAudioElement
                        if (!isMediaElementPlaying(audio)) {
                            audio.play().catch(() => {})
                        }
                        return // exit early as we only expect one PostHog audio element per added node
                    }

                    // Also check for any audio elements within the added element - just in case!
                    const audioElements = element.querySelectorAll('audio[data-posthog-recording="true"]')
                    audioElements.forEach((audioElement) => {
                        const audio = audioElement as HTMLAudioElement
                        if (!isMediaElementPlaying(audio)) {
                            audio.play().catch(() => {})
                        }
                    })
                }
            })
        })
    })

    observer.observe(targetElement, {
        childList: true,
        subtree: true,
    })

    return observer
}
