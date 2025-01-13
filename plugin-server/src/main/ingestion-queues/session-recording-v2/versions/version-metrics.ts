import { Counter } from 'prom-client'

export class VersionMetrics {
    private static instance: VersionMetrics
    private readonly libVersionWarningCounter: Counter

    public constructor() {
        this.libVersionWarningCounter = new Counter({
            name: 'lib_version_warning_counter',
            help: 'the number of times we have seen a message with a lib version that is too old, each _might_ cause an ingestion warning if not debounced',
        })
    }

    public static getInstance(): VersionMetrics {
        if (!VersionMetrics.instance) {
            VersionMetrics.instance = new VersionMetrics()
        }
        return VersionMetrics.instance
    }

    public incrementLibVersionWarning(): void {
        this.libVersionWarningCounter.inc(1)
    }
}
