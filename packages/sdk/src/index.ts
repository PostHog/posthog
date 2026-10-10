import { createNamespaces, type GeneratedClient } from './generated/client.js'
import { Runtime } from './runtime/client.js'
import type { PostHogClientOptions, ProjectContext, RequestOptions } from './types.js'

export { PostHogError } from './errors.js'
export type * from './types.js'
export type * from './generated/index.js'

export interface PostHogProjectClient extends GeneratedClient {
    readonly projectId: number
    context(options?: RequestOptions): Promise<ProjectContext>
}

export interface PostHogClient extends GeneratedClient {
    /** Resolves and pins the default project without changing the user's PostHog settings. */
    context(options?: RequestOptions): Promise<ProjectContext>
    /** Returns an independent scope using this client's configuration and credential. */
    project(projectId: number): PostHogProjectClient
}

export function createPostHogClient(options: PostHogClientOptions = {}): PostHogClient {
    const runtime = new Runtime(options)
    return {
        ...createNamespaces(runtime),
        context: (requestOptions) => runtime.context(requestOptions),
        project: (projectId) => {
            const scoped = runtime.scope(projectId)
            return {
                projectId,
                ...createNamespaces(scoped),
                context: (requestOptions) => scoped.context(requestOptions),
            }
        },
    }
}

/** Configuration and credentials are read lazily; importing the package never makes a request. */
export const client: PostHogClient = createPostHogClient()

export default client
