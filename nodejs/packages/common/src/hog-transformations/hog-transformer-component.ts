import { HogTransformer } from './hog-transformer.interface'

/**
 * Scope owner for a hog transformer: starts it on `start()` and stops it on
 * `stop()`, so its lifetime is tied to the owning scope. The concrete
 * transformer is supplied by the caller via a factory (the implementation
 * lives in cdp), so ingestion scopes own its lifecycle without importing cdp.
 */
export class HogTransformerComponent {
    constructor(private readonly create: () => HogTransformer) {}

    async start(): Promise<{ value: HogTransformer; stop: () => Promise<void> }> {
        const hogTransformer = this.create()
        await hogTransformer.start()
        return { value: hogTransformer, stop: () => hogTransformer.stop() }
    }
}
