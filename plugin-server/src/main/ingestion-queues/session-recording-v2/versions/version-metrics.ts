import { Counter } from 'prom-client'

export class VersionMetrics {
    private static readonly libVersionWarningCounter = new Counter({
        name: 'recording_blob_ingestion_v2_lib_version_warning_counter',
        help: 'the number of times we have seen a message with a lib version that is too old, each _might_ cause an ingestion warning if not debounced',
    })

    public static incrementLibVersionWarning(): void {
        this.libVersionWarningCounter.inc(1)
    }
}
