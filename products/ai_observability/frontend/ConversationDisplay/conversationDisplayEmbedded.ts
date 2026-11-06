import { createContext, useContext } from 'react'

import { isTrustedPostHogUrl } from 'lib/utils/trustedUrl'

/**
 * True while a conversation renders outside AI observability, such as in a support ticket's sidebar.
 * Trace discussions need the trace's own scene, so they are hidden there. Images from hosts other than
 * PostHog show as links, because loading them would send the viewer's IP address to that host as soon
 * as the conversation opens.
 */
export const ConversationDisplayEmbeddedContext = createContext(false)

export function useConversationDisplayEmbedded(): boolean {
    return useContext(ConversationDisplayEmbeddedContext)
}

/** A `data:` image makes no request, and a PostHog URL reaches no third party. */
export function canLoadImageWhileEmbedded(src: string): boolean {
    return src.startsWith('data:') || isTrustedPostHogUrl(src)
}
