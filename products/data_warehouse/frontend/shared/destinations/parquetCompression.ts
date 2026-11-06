/**
 * Mirrors `ParquetCompression` in the S3 and Azure Blob writers, which reject an unsupported
 * value before reading a batch. An option added here alone fails the sync, not the form.
 */
export const PARQUET_COMPRESSION_OPTIONS: { value: string; label: string }[] = [
    { value: 'zstd', label: 'zstd' },
    { value: 'snappy', label: 'snappy' },
    { value: 'gzip', label: 'gzip' },
    { value: 'brotli', label: 'brotli' },
    { value: 'lz4', label: 'lz4' },
    { value: 'none', label: 'None' },
]

export const DEFAULT_PARQUET_COMPRESSION = 'zstd'
