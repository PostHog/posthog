export class LazyClient<TClient> {
    private loaded: Promise<TClient> | undefined
    private facade: TClient | undefined

    constructor(
        private readonly loadClient: () => Promise<TClient>,
        private readonly createFacade: (load: () => Promise<TClient>) => TClient
    ) {}

    private load(): Promise<TClient> {
        this.loaded ??= this.loadClient().catch((error: unknown) => {
            this.loaded = undefined
            throw error
        })
        return this.loaded
    }

    get client(): TClient {
        this.facade ??= this.createFacade(() => this.load())
        return this.facade
    }
}
