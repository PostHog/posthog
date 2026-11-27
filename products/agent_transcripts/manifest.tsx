/**
 * Product manifest for agent_transcripts.
 *
 * Defines scenes, routes, URLs, and navigation for this product.
 */
import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'AgentTranscripts',
    scenes: {
        AgentTranscript: {
            name: 'Share your agent transcript',
            import: () => import('./frontend/scenes/AgentTranscriptScene'),
            organizationBased: true,
            description: 'Upload the transcript of the conversation where an AI agent set up PostHog.',
        },
    },
    routes: {
        // pinned: the request card and emails link here, so renaming the path breaks links already sent
        '/agent-transcript': ['AgentTranscript', 'agentTranscript'],
    },
    redirects: {},
    urls: {
        agentTranscript: (): string => '/agent-transcript',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
