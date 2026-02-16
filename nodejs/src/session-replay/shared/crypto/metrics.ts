import { Counter } from 'prom-client'

export class CryptoMetrics {
    private static readonly cryptoIntegrityChecks = new Counter({
        name: 'recording_blob_ingestion_v2_crypto_integrity_checks_total',
        help: 'Number of encrypt-decrypt round-trip integrity checks performed',
    })

    private static readonly cryptoIntegritySuccesses = new Counter({
        name: 'recording_blob_ingestion_v2_crypto_integrity_successes_total',
        help: 'Number of encrypt-decrypt round-trip integrity checks that succeeded',
    })

    private static readonly cryptoIntegrityFailures = new Counter({
        name: 'recording_blob_ingestion_v2_crypto_integrity_failures_total',
        help: 'Number of encrypt-decrypt round-trip integrity checks that failed',
        labelNames: ['type'],
    })

    public static incrementCryptoIntegrityChecks(): void {
        this.cryptoIntegrityChecks.inc()
    }

    public static incrementCryptoIntegritySuccesses(): void {
        this.cryptoIntegritySuccesses.inc()
    }

    public static incrementCryptoIntegrityFailures(
        type: 'mismatch' | 'decompression' | 'json_parse' | 'exception'
    ): void {
        this.cryptoIntegrityFailures.labels({ type }).inc()
    }
}
