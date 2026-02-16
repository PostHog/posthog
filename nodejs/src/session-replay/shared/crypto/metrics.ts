import { Counter } from 'prom-client'

export class CryptoMetrics {
    private static readonly cryptoIntegrityChecks = new Counter({
        name: 'recording_blob_ingestion_v2_crypto_integrity_checks_total',
        help: 'Number of encrypt-decrypt round-trip integrity checks performed',
    })

    private static readonly cryptoIntegrityFailures = new Counter({
        name: 'recording_blob_ingestion_v2_crypto_integrity_failures_total',
        help: 'Number of encrypt-decrypt round-trip integrity checks that failed',
    })

    public static incrementCryptoIntegrityChecks(): void {
        this.cryptoIntegrityChecks.inc()
    }

    public static incrementCryptoIntegrityFailures(): void {
        this.cryptoIntegrityFailures.inc()
    }
}
