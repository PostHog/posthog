use std::{
    path::{Path, PathBuf},
    sync::{Arc, OnceLock},
};

use anyhow::{Context, Result};
use rocksdb::{
    checkpoint::Checkpoint, BlockBasedOptions, BoundColumnFamily, Cache, ColumnFamilyDescriptor,
    DBCompressionType, DBWithThreadMode, MultiThreaded, Options, WriteBatch, WriteBufferManager,
    WriteOptions,
};
use std::time::Instant;
use tracing::error;

use crate::metrics::MetricsHelper;
use crate::rocksdb::metrics_consts::*;

// ── RocksDbConfig defaults (env-overridable via Config) ─────────────────────

const DEFAULT_SHARED_CACHE_SIZE_BYTES: usize = 2048 * 1024 * 1024; // 2 GB
const DEFAULT_TOTAL_WRITE_BUFFER_SIZE_BYTES: usize = 2048 * 1024 * 1024; // 2 GB across ALL stores
const DEFAULT_MAX_BACKGROUND_JOBS_CAP: i32 = 2;
const DEFAULT_PARALLELISM_FALLBACK: usize = 2;
const DEFAULT_WRITE_BUFFER_SIZE_BYTES: usize = 64 * 1024 * 1024; // 64 MB per memtable
const DEFAULT_TARGET_FILE_SIZE_BASE_BYTES: u64 = 256 * 1024 * 1024; // 256 MB SST files
const DEFAULT_MAX_OPEN_FILES: i32 = 1024;
// L0 compaction thresholds — higher values batch more L0 files before compaction,
// reducing compaction frequency at the cost of higher read amplification.
const DEFAULT_L0_COMPACTION_TRIGGER: i32 = 8; // RocksDB default: 4
const DEFAULT_L0_SLOWDOWN_WRITES_TRIGGER: i32 = 20;
const DEFAULT_L0_STOP_WRITES_TRIGGER: i32 = 36;

// ── rocksdb_options() fixed settings (not env-overridable) ──────────────────

/// Bloom filter bits per key — 10 bits ≈ 1% false-positive rate.
const BLOOM_FILTER_BITS_PER_KEY: f64 = 10.0;
/// Timestamp key prefix length for SliceTransform (8-byte epoch seconds).
pub const TIMESTAMP_PREFIX_LEN: usize = 8;
/// 2 write buffers: one active for writes, one flushing to disk.
const MAX_WRITE_BUFFER_NUMBER: i32 = 2;
/// Merge every buffer immediately — avoids batching delay before flush.
const MIN_WRITE_BUFFER_NUMBER_TO_MERGE: i32 = 1;
/// Periodic fsync interval for SST and WAL data.
const BYTES_PER_SYNC: u64 = 1024 * 1024; // 1 MB
/// Readahead buffer for compaction I/O.
const COMPACTION_READAHEAD_SIZE: usize = 2 * 1024 * 1024; // 2 MB

// Universal compaction tuning — we don't call optimize_universal_style_compaction()
// because it forces Snappy compression. Instead, manual config with relaxed triggers
// to reduce compaction frequency on slow PVC storage.
const UNIVERSAL_SIZE_RATIO: i32 = 10; // Allow 10% size difference before compacting (default: 1)
const UNIVERSAL_MIN_MERGE_WIDTH: i32 = 2;
const UNIVERSAL_MAX_MERGE_WIDTH: i32 = 16;
const UNIVERSAL_MAX_SIZE_AMPLIFICATION_PERCENT: i32 = 200; // Allow 2x space amplification
const DEFAULT_UNIVERSAL_COMPRESSION_SIZE_PERCENT: i32 = -1; // Compress all levels

// ── Compression type parsing ─────────────────────────────────────────────────

pub fn parse_compression_type(s: &str) -> Result<DBCompressionType> {
    match s.to_lowercase().trim() {
        "none" => Ok(DBCompressionType::None),
        "snappy" => Ok(DBCompressionType::Snappy),
        "zlib" => Ok(DBCompressionType::Zlib),
        "lz4" => Ok(DBCompressionType::Lz4),
        "lz4hc" => Ok(DBCompressionType::Lz4hc),
        "zstd" => Ok(DBCompressionType::Zstd),
        other => anyhow::bail!("unknown compression type: {other}"),
    }
}

pub fn parse_compression_per_level(s: &str) -> Result<Vec<DBCompressionType>> {
    s.split(',').map(parse_compression_type).collect()
}

/// RocksDB tuning knobs exposed as env vars for per-deploy overrides.
/// Concrete types — all values fully resolved at construction time.
/// Tests use `RocksDbConfig::default()` which mirrors the constants above.
#[derive(Debug, Clone)]
pub struct RocksDbConfig {
    pub shared_cache_size_bytes: usize,
    pub total_write_buffer_size_bytes: usize,
    pub max_background_jobs: i32,
    pub write_buffer_size_bytes: usize,
    pub target_file_size_base_bytes: u64,
    pub max_open_files: i32,
    pub l0_compaction_trigger: i32,
    pub l0_slowdown_writes_trigger: i32,
    pub l0_stop_writes_trigger: i32,
    /// Whether the write buffer manager should stall writes when memory is full.
    /// false = backpressure handled at Kafka level instead.
    pub write_buffer_manager_allow_stall: bool,
    /// Default compression type applied to all SST levels when compression_per_level is None.
    pub compression_type: DBCompressionType,
    /// Per-level compression overrides. When set, takes precedence over compression_type.
    /// In Universal compaction, universal_compression_size_percent must be >= 0 for this to take effect.
    pub compression_per_level: Option<Vec<DBCompressionType>>,
    /// Compression override for the bottommost sorted run (e.g. Zstd for cold data).
    pub bottommost_compression_type: Option<DBCompressionType>,
    /// Controls what fraction of data is compressed in Universal compaction.
    /// -1 = compress all (per-level settings ignored), >= 0 = enable per-level compression.
    pub universal_compression_size_percent: i32,
}

impl Default for RocksDbConfig {
    fn default() -> Self {
        let num_threads = std::thread::available_parallelism()
            .map(|p| p.get())
            .unwrap_or(DEFAULT_PARALLELISM_FALLBACK);
        Self {
            shared_cache_size_bytes: DEFAULT_SHARED_CACHE_SIZE_BYTES,
            total_write_buffer_size_bytes: DEFAULT_TOTAL_WRITE_BUFFER_SIZE_BYTES,
            max_background_jobs: std::cmp::min(num_threads as i32, DEFAULT_MAX_BACKGROUND_JOBS_CAP),
            write_buffer_size_bytes: DEFAULT_WRITE_BUFFER_SIZE_BYTES,
            target_file_size_base_bytes: DEFAULT_TARGET_FILE_SIZE_BASE_BYTES,
            max_open_files: DEFAULT_MAX_OPEN_FILES,
            l0_compaction_trigger: DEFAULT_L0_COMPACTION_TRIGGER,
            l0_slowdown_writes_trigger: DEFAULT_L0_SLOWDOWN_WRITES_TRIGGER,
            l0_stop_writes_trigger: DEFAULT_L0_STOP_WRITES_TRIGGER,
            write_buffer_manager_allow_stall: false,
            compression_type: DBCompressionType::Lz4,
            compression_per_level: None,
            bottommost_compression_type: None,
            universal_compression_size_percent: DEFAULT_UNIVERSAL_COMPRESSION_SIZE_PERCENT,
        }
    }
}

#[derive(Debug, Clone)]
pub struct RocksDbStore {
    pub(crate) db: Arc<DBWithThreadMode<MultiThreaded>>,
    path_location: PathBuf,
    metrics: MetricsHelper,
}

// Shared block cache for all RocksDB instances — initialized via init_shared_resources()
static SHARED_BLOCK_CACHE: OnceLock<Arc<Cache>> = OnceLock::new();

// Shared write buffer manager to limit total memory used for write buffers
static SHARED_WRITE_BUFFER_MANAGER: OnceLock<Arc<WriteBufferManager>> = OnceLock::new();

/// Initialize shared RocksDB resources (block cache, write buffer manager).
/// Idempotent — safe to call multiple times; first call wins.
/// Called explicitly in Service::new() and as a fallback in rocksdb_options().
pub fn init_shared_resources(config: &RocksDbConfig) {
    SHARED_BLOCK_CACHE
        .get_or_init(|| Arc::new(Cache::new_lru_cache(config.shared_cache_size_bytes)));

    SHARED_WRITE_BUFFER_MANAGER.get_or_init(|| {
        Arc::new(WriteBufferManager::new_write_buffer_manager(
            config.total_write_buffer_size_bytes,
            config.write_buffer_manager_allow_stall,
        ))
    });
}

fn block_based_table_options() -> BlockBasedOptions {
    let mut block_opts = BlockBasedOptions::default();
    // Bloom filter reduces full-key lookups during dedup checks
    block_opts.set_bloom_filter(BLOOM_FILTER_BITS_PER_KEY, false);
    block_opts.set_cache_index_and_filter_blocks(true);
    block_opts.set_pin_l0_filter_and_index_blocks_in_cache(true);
    block_opts.set_whole_key_filtering(true);
    block_opts.set_partition_filters(true);
    block_opts.set_pin_top_level_index_and_filter(true);
    // Use shared block cache across all stores and column families
    block_opts.set_block_cache(
        SHARED_BLOCK_CACHE
            .get()
            .expect("shared block cache not initialized"),
    );
    block_opts
}

/// Build column family options with all tuning from `RocksDbConfig`.
/// CF options don't inherit from DB options, so this must explicitly set
/// every option that matters for the CF's performance and compression.
pub fn column_family_options(config: &RocksDbConfig) -> Options {
    // Ensure shared resources are initialized (idempotent fallback for tests)
    init_shared_resources(config);

    let mut opts = Options::default();

    opts.set_block_based_table_factory(&block_based_table_options());

    // Write buffer tuning — larger buffers = fewer flushes = less I/O on PVC storage.
    opts.set_write_buffer_size(config.write_buffer_size_bytes);
    opts.set_max_write_buffer_number(MAX_WRITE_BUFFER_NUMBER);
    opts.set_min_write_buffer_number_to_merge(MIN_WRITE_BUFFER_NUMBER_TO_MERGE);

    opts.set_target_file_size_base(config.target_file_size_base_bytes);

    // Universal compaction: lower write amplification for write-heavy workloads
    opts.set_compaction_style(rocksdb::DBCompactionStyle::Universal);
    let mut universal_opts = rocksdb::UniversalCompactOptions::default();
    universal_opts.set_size_ratio(UNIVERSAL_SIZE_RATIO);
    universal_opts.set_min_merge_width(UNIVERSAL_MIN_MERGE_WIDTH);
    universal_opts.set_max_merge_width(UNIVERSAL_MAX_MERGE_WIDTH);
    universal_opts.set_max_size_amplification_percent(UNIVERSAL_MAX_SIZE_AMPLIFICATION_PERCENT);
    universal_opts.set_compression_size_percent(config.universal_compression_size_percent);
    opts.set_universal_compaction_options(&universal_opts);

    // L0 compaction triggers
    opts.set_level_zero_file_num_compaction_trigger(config.l0_compaction_trigger);
    opts.set_level_zero_slowdown_writes_trigger(config.l0_slowdown_writes_trigger);
    opts.set_level_zero_stop_writes_trigger(config.l0_stop_writes_trigger);

    // Compression
    if let Some(ref per_level) = config.compression_per_level {
        opts.set_compression_per_level(per_level);
    } else {
        opts.set_compression_type(config.compression_type);
    }
    if let Some(bottommost) = config.bottommost_compression_type {
        opts.set_bottommost_compression_type(bottommost);
        if bottommost == DBCompressionType::Zstd {
            opts.set_bottommost_zstd_max_train_bytes(0, true);
        }
    }

    opts
}

fn rocksdb_options(config: &RocksDbConfig) -> Options {
    // Start with column_family_options() as the base — these settings apply to the
    // default CF and are shared with custom CFs via column_family_options().
    let mut opts = column_family_options(config);

    // DB-level settings (not per-CF)
    opts.create_if_missing(true);
    opts.set_atomic_flush(true);
    opts.create_missing_column_families(true);

    // CRITICAL: Use shared write buffer manager to limit total memory across all stores
    opts.set_write_buffer_manager(
        SHARED_WRITE_BUFFER_MANAGER
            .get()
            .expect("shared write buffer manager not initialized"),
    );

    // Limit background jobs to reduce I/O contention when many partitions share a disk
    opts.increase_parallelism(config.max_background_jobs);
    opts.set_max_background_jobs(config.max_background_jobs);

    opts.set_paranoid_checks(true);
    opts.set_bytes_per_sync(BYTES_PER_SYNC);
    opts.set_wal_bytes_per_sync(BYTES_PER_SYNC);

    // Let OS page cache buffer writes — critical for PVC storage
    opts.set_use_direct_reads(false);
    opts.set_use_direct_io_for_flush_and_compaction(false);
    opts.set_compaction_readahead_size(COMPACTION_READAHEAD_SIZE);

    opts.set_disable_auto_compactions(false);
    opts.set_max_open_files(config.max_open_files);

    // CRITICAL: Disable mmap with many partitions to avoid virtual memory explosion
    opts.set_allow_mmap_reads(false);
    opts.set_allow_mmap_writes(false);

    opts
}

impl RocksDbStore {
    pub fn new<P: AsRef<Path>>(
        path: P,
        cf_descriptors: Vec<ColumnFamilyDescriptor>,
        metrics: MetricsHelper,
        rocksdb_config: &RocksDbConfig,
    ) -> Result<Self> {
        let path_ref = path.as_ref();
        let opts = rocksdb_options(rocksdb_config);

        let db =
            DBWithThreadMode::<MultiThreaded>::open_cf_descriptors(&opts, path_ref, cf_descriptors)
                .context("Failed to open RocksDB")?;

        Ok(Self {
            db: Arc::new(db),
            path_location: path_ref.to_path_buf(),
            metrics,
        })
    }

    pub fn get(&self, cf_name: &str, key: &[u8]) -> Result<Option<Vec<u8>>> {
        let start_time = Instant::now();

        // Track read operation with column family label
        self.metrics
            .counter(ROCKSDB_READ_OPERATIONS_COUNTER)
            .with_label("column_family", cf_name)
            .increment(1);

        let cf = self.get_cf_handle(cf_name)?;
        let result = self
            .db
            .get_cf(&cf, key)
            .context("Failed to get key from RocksDB");

        let duration = start_time.elapsed();
        self.metrics
            .histogram(ROCKSDB_READ_DURATION_HISTOGRAM)
            .with_label("column_family", cf_name)
            .record(duration.as_secs_f64());

        if result.is_err() {
            self.metrics.counter(ROCKSDB_ERRORS_COUNTER).increment(1);
        }

        result
    }

    pub fn multi_get(&self, cf_name: &str, keys: Vec<&[u8]>) -> Result<Vec<Option<Vec<u8>>>> {
        let start_time = Instant::now();
        self.metrics
            .counter(ROCKSDB_READ_OPERATIONS_COUNTER)
            .with_label("column_family", cf_name)
            .increment(1);

        let result = self.multi_get_internal(cf_name, keys);

        let duration = start_time.elapsed();
        self.metrics
            .histogram(ROCKSDB_MULTI_GET_DURATION_HISTOGRAM)
            .with_label("column_family", cf_name)
            .record(duration.as_secs_f64());

        if result.is_err() {
            self.metrics.counter(ROCKSDB_ERRORS_COUNTER).increment(1);
        }

        result
    }

    fn multi_get_internal(&self, cf_name: &str, keys: Vec<&[u8]>) -> Result<Vec<Option<Vec<u8>>>> {
        let cf = self.get_cf_handle(cf_name)?;

        let keys_with_cf: Vec<_> = keys.iter().map(|k| (&cf, k)).collect();
        let results = self.db.multi_get_cf(keys_with_cf);

        results
            .into_iter()
            .map(|r| r.context("Failed to get key"))
            .collect()
    }

    pub fn put(&self, cf_name: &str, key: &[u8], value: &[u8]) -> Result<()> {
        let start_time = Instant::now();
        self.metrics
            .counter(ROCKSDB_WRITE_OPERATIONS_COUNTER)
            .with_label("column_family", cf_name)
            .increment(1);

        let result = self.put_internal(cf_name, key, value);

        let duration = start_time.elapsed();
        self.metrics
            .histogram(ROCKSDB_WRITE_DURATION_HISTOGRAM)
            .with_label("column_family", cf_name)
            .record(duration.as_secs_f64());

        if result.is_err() {
            self.metrics.counter(ROCKSDB_ERRORS_COUNTER).increment(1);
        }

        result
    }

    fn put_internal(&self, cf_name: &str, key: &[u8], value: &[u8]) -> Result<()> {
        let cf = self.get_cf_handle(cf_name)?;
        self.db.put_cf(&cf, key, value).context("Failed to put key")
    }

    pub fn put_batch(&self, cf_name: &str, entries: Vec<(&[u8], &[u8])>) -> Result<()> {
        let start_time = Instant::now();
        let batch_size = entries.len();
        self.metrics
            .counter(ROCKSDB_BATCH_WRITE_OPERATIONS_COUNTER)
            .with_label("column_family", cf_name)
            .increment(1);

        let result = self.put_batch_internal(cf_name, entries);

        let duration = start_time.elapsed();
        self.metrics
            .histogram(ROCKSDB_BATCH_WRITE_DURATION_HISTOGRAM)
            .with_label("column_family", cf_name)
            .record(duration.as_secs_f64());

        if result.is_ok() {
            // Track successful batch size
            self.metrics
                .histogram(ROCKSDB_BATCH_SIZE_HISTOGRAM)
                .with_label("column_family", cf_name)
                .record(batch_size as f64);
        } else {
            self.metrics.counter(ROCKSDB_ERRORS_COUNTER).increment(1);
        }

        result
    }

    fn put_batch_internal(&self, cf_name: &str, entries: Vec<(&[u8], &[u8])>) -> Result<()> {
        let cf = self.get_cf_handle(cf_name)?;
        let entry_count = entries.len();
        let mut batch = WriteBatch::default();
        for (key, value) in entries {
            batch.put_cf(&cf, key, value);
        }
        let batch_size_bytes = batch.size_in_bytes();
        let mut write_opts = WriteOptions::default();
        write_opts.set_sync(false);
        self.db.write_opt(batch, &write_opts).map_err(|e| {
            error!(
                cf_name = cf_name,
                entry_count = entry_count,
                batch_size_bytes = batch_size_bytes,
                db_path = %self.path_location.display(),
                rocksdb_error = ?e,
                "RocksDB write_opt failed"
            );
            anyhow::Error::from(e).context(format!(
                "Failed to put batch ({} entries, {} bytes)",
                entry_count, batch_size_bytes
            ))
        })
    }

    pub fn delete_range(&self, cf_name: &str, start: &[u8], end: &[u8]) -> Result<()> {
        let cf = self.get_cf_handle(cf_name)?;
        self.db
            .delete_range_cf(&cf, start, end)
            .context("Failed to delete range")
    }

    pub fn delete(&self, cf_name: &str, key: &[u8]) -> Result<()> {
        let cf = self.get_cf_handle(cf_name)?;
        self.db.delete_cf(&cf, key).context("Failed to delete key")
    }

    /// Trigger compaction for a column family within a key range.
    /// This is non-blocking - compaction runs asynchronously in the background.
    /// After delete_range, this helps RocksDB prioritize reclaiming space from tombstones.
    pub fn compact_range(&self, cf_name: &str, start: Option<&[u8]>, end: Option<&[u8]>) {
        if let Ok(cf) = self.get_cf_handle(cf_name) {
            self.db.compact_range_cf(&cf, start, end);
        }
    }

    pub fn get_cf_handle(&self, cf_name: &str) -> Result<Arc<BoundColumnFamily<'_>>> {
        self.db
            .cf_handle(cf_name)
            .context("Column family not found")
    }

    pub fn get_db_size(&self, cf_name: &str) -> Result<u64> {
        let cf = self.get_cf_handle(cf_name)?;
        // Try to get SST files size
        let sst_size = self
            .db
            .property_int_value_cf(&cf, "rocksdb.total-sst-files-size")?
            .unwrap_or(0);

        Ok(sst_size)
    }

    /// Update database metrics (size, SST file count, etc.)
    /// This should be called periodically to emit current database state
    pub fn update_db_metrics(&self, cf_name: &str) -> Result<()> {
        let cf = self.get_cf_handle(cf_name)?;

        // Update database size metric with column family label
        let db_size = self.get_db_size(cf_name)?;
        self.metrics
            .gauge(ROCKSDB_SIZE_BYTES_GAUGE)
            .with_label("column_family", cf_name)
            .set(db_size as f64);

        // Update SST file count with column family label
        let sst_files = self.get_sst_file_names(cf_name)?;
        self.metrics
            .gauge(ROCKSDB_SST_FILES_COUNT_GAUGE)
            .with_label("column_family", cf_name)
            .set(sst_files.len() as f64);

        // Update estimated key count metric
        if let Ok(Some(estimate_keys)) = self
            .db
            .property_int_value_cf(&cf, "rocksdb.estimate-num-keys")
        {
            self.metrics
                .gauge(ROCKSDB_ESTIMATE_NUM_KEYS_GAUGE)
                .with_label("column_family", cf_name)
                .set(estimate_keys as f64);
        }

        Ok(())
    }

    pub fn flush_cf(&self, cf_name: &str) -> Result<()> {
        let start_time = Instant::now();

        let result = self.flush_cf_internal(cf_name);

        let duration = start_time.elapsed();
        self.metrics
            .histogram(ROCKSDB_FLUSH_DURATION_HISTOGRAM)
            .with_label("column_family", cf_name)
            .record(duration.as_secs_f64());

        if result.is_err() {
            self.metrics.counter(ROCKSDB_ERRORS_COUNTER).increment(1);
        }

        result
    }

    pub fn flush_all_cf(&self) -> Result<()> {
        let mut flush_opts = rocksdb::FlushOptions::default();
        flush_opts.set_wait(true);
        let start_time = Instant::now();
        let result = self.db.flush_opt(&flush_opts);
        let duration = start_time.elapsed();
        self.metrics
            .histogram(ROCKSDB_FLUSH_DURATION_HISTOGRAM)
            .record(duration.as_secs_f64());
        match result {
            Ok(_) => Ok(()),
            Err(e) => {
                self.metrics.counter(ROCKSDB_ERRORS_COUNTER).increment(1);
                Err(anyhow::Error::from(e).context("Failed to flush"))
            }
        }
    }

    fn flush_cf_internal(&self, cf_name: &str) -> Result<()> {
        let mut flush_opts = rocksdb::FlushOptions::default();
        flush_opts.set_wait(true);
        let cf = self.get_cf_handle(cf_name)?;
        self.db
            .flush_cf_opt(&cf, &flush_opts)
            .context("Failed to flush")
    }

    /// Flush the WAL (Write-Ahead Log) to ensure durability
    /// Setting sync=true ensures WAL is synced to disk before returning
    pub fn flush_wal(&self, sync: bool) -> Result<()> {
        self.db
            .flush_wal(sync)
            .with_context(|| format!("Failed to flush WAL (sync={sync})"))
    }

    /// Get the latest sequence number from the database
    /// This represents the current state of the database and can be used to verify checkpoint consistency
    pub fn latest_sequence_number(&self) -> u64 {
        self.db.latest_sequence_number()
    }

    /// Create an incremental checkpoint at the specified path
    /// This creates a point-in-time snapshot that can be used for recovery
    pub fn create_checkpoint<P: AsRef<Path>>(&self, checkpoint_path: P) -> Result<()> {
        let start_time = Instant::now();
        self.metrics
            .counter(ROCKSDB_CHECKPOINT_OPERATIONS_COUNTER)
            .increment(1);

        let result = self.create_checkpoint_internal(checkpoint_path);

        let duration = start_time.elapsed();
        self.metrics
            .histogram(ROCKSDB_CHECKPOINT_DURATION_HISTOGRAM)
            .record(duration.as_secs_f64());

        if result.is_err() {
            self.metrics.counter(ROCKSDB_ERRORS_COUNTER).increment(1);
        }

        result
    }

    fn create_checkpoint_internal<P: AsRef<Path>>(&self, checkpoint_path: P) -> Result<()> {
        let checkpoint = Checkpoint::new(&self.db).context("Failed to create checkpoint object")?;

        checkpoint
            .create_checkpoint(checkpoint_path)
            .context("Failed to create checkpoint")
    }

    /// Get the database path location
    pub fn get_path(&self) -> &PathBuf {
        &self.path_location
    }

    /// Get current SST file names for tracking incremental changes
    pub fn get_sst_file_names(&self, cf_name: &str) -> Result<Vec<String>> {
        let live_files = self
            .db
            .live_files()
            .context("Failed to get live files metadata")?;

        Ok(live_files
            .into_iter()
            .filter(|f| f.column_family_name == cf_name)
            .map(|f| f.name)
            .collect())
    }

    /// Compare SST files between two sets to find differences
    pub fn compute_sst_delta(old_files: &[String], new_files: &[String]) -> SstDelta {
        let old_set: std::collections::HashSet<&String> = old_files.iter().collect();
        let new_set: std::collections::HashSet<&String> = new_files.iter().collect();

        let added_files: Vec<String> = new_set
            .difference(&old_set)
            .map(|s| s.to_string())
            .collect();

        let removed_files: Vec<String> = old_set
            .difference(&new_set)
            .map(|s| s.to_string())
            .collect();

        let unchanged_files: Vec<String> = old_set
            .intersection(&new_set)
            .map(|s| s.to_string())
            .collect();

        SstDelta {
            added_files,
            removed_files,
            unchanged_files,
        }
    }
}

/// Delta between two SST file sets
#[derive(Debug, Clone)]
pub struct SstDelta {
    pub added_files: Vec<String>,
    pub removed_files: Vec<String>,
    pub unchanged_files: Vec<String>,
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    const TEST_CF: &str = "test_cf";

    fn create_test_store() -> (RocksDbStore, TempDir) {
        let temp_dir = TempDir::new().unwrap();
        let cf_descriptor = ColumnFamilyDescriptor::new(TEST_CF, Options::default());
        let metrics = MetricsHelper::new().with_label("test", "true");
        let store = RocksDbStore::new(
            temp_dir.path(),
            vec![cf_descriptor],
            metrics,
            &RocksDbConfig::default(),
        )
        .unwrap();
        (store, temp_dir)
    }

    #[test]
    fn test_store_creation() {
        let (store, _temp_dir) = create_test_store();

        // Verify we can get the column family handle
        let cf_handle = store.get_cf_handle(TEST_CF);
        assert!(cf_handle.is_ok());
    }

    #[test]
    fn test_put_and_multi_get() {
        let (store, _temp_dir) = create_test_store();

        let key1 = b"key1";
        let key2 = b"key2";
        let value1 = b"value1";
        let value2 = b"value2";

        // Put values
        store.put(TEST_CF, key1, value1).unwrap();
        store.put(TEST_CF, key2, value2).unwrap();

        // Multi-get
        let keys = vec![key1.as_slice(), key2.as_slice()];
        let results = store.multi_get(TEST_CF, keys).unwrap();

        assert_eq!(results.len(), 2);
        assert_eq!(results[0].as_ref().unwrap(), value1);
        assert_eq!(results[1].as_ref().unwrap(), value2);
    }

    #[test]
    fn test_multi_get_missing_keys() {
        let (store, _temp_dir) = create_test_store();

        let key1 = b"existing_key";
        let key2 = b"missing_key";
        let value1 = b"value1";

        // Put only one key
        store.put(TEST_CF, key1, value1).unwrap();

        // Multi-get both keys
        let keys = vec![key1.as_slice(), key2.as_slice()];
        let results = store.multi_get(TEST_CF, keys).unwrap();

        assert_eq!(results.len(), 2);
        assert_eq!(results[0].as_ref().unwrap(), value1);
        assert!(results[1].is_none());
    }

    #[test]
    fn test_put_batch() {
        let (store, _temp_dir) = create_test_store();

        let entries = vec![
            (b"key1".as_slice(), b"value1".as_slice()),
            (b"key2".as_slice(), b"value2".as_slice()),
            (b"key3".as_slice(), b"value3".as_slice()),
        ];

        // Batch put
        store.put_batch(TEST_CF, entries.clone()).unwrap();

        // Verify all entries were stored
        let keys: Vec<&[u8]> = entries.iter().map(|(k, _)| *k).collect();
        let results = store.multi_get(TEST_CF, keys).unwrap();

        for (i, (_, expected_value)) in entries.iter().enumerate() {
            assert_eq!(results[i].as_ref().unwrap(), expected_value);
        }
    }

    #[test]
    fn test_delete_range() {
        let (store, _temp_dir) = create_test_store();

        // Put some keys
        store.put(TEST_CF, b"key1", b"value1").unwrap();
        store.put(TEST_CF, b"key2", b"value2").unwrap();
        store.put(TEST_CF, b"key3", b"value3").unwrap();
        store.put(TEST_CF, b"key4", b"value4").unwrap();

        // Delete range key2 to key4 (exclusive)
        store.delete_range(TEST_CF, b"key2", b"key4").unwrap();

        // Check what remains
        let keys = vec![
            b"key1".as_slice(),
            b"key2".as_slice(),
            b"key3".as_slice(),
            b"key4".as_slice(),
        ];
        let results = store.multi_get(TEST_CF, keys).unwrap();

        assert!(results[0].is_some()); // key1 should remain
        assert!(results[1].is_none()); // key2 should be deleted
        assert!(results[2].is_none()); // key3 should be deleted
        assert!(results[3].is_some()); // key4 should remain (exclusive end)
    }

    #[test]
    fn test_invalid_column_family() {
        let (store, _temp_dir) = create_test_store();

        let result = store.put("nonexistent_cf", b"key", b"value");
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("Column family not found"));
    }

    #[test]
    fn test_empty_multi_get() {
        let (store, _temp_dir) = create_test_store();

        let keys: Vec<&[u8]> = vec![];
        let results = store.multi_get(TEST_CF, keys).unwrap();
        assert!(results.is_empty());
    }

    #[test]
    fn test_empty_put_batch() {
        let (store, _temp_dir) = create_test_store();

        let entries: Vec<(&[u8], &[u8])> = vec![];
        let result = store.put_batch(TEST_CF, entries);
        assert!(result.is_ok());
    }

    #[test]
    fn test_create_checkpoint() {
        let (store, _temp_dir) = create_test_store();

        // Add some data
        store.put(TEST_CF, b"key1", b"value1").unwrap();
        store.put(TEST_CF, b"key2", b"value2").unwrap();

        // Create checkpoint
        let checkpoint_dir = TempDir::new().unwrap();
        let checkpoint_path = checkpoint_dir.path().join("checkpoint");

        let result = store.create_checkpoint(&checkpoint_path);
        assert!(result.is_ok());

        // Verify checkpoint directory was created and contains data
        assert!(checkpoint_path.exists());
        assert!(checkpoint_path.is_dir());
    }

    #[test]
    fn test_checkpoint_recovery() {
        let temp_dir = TempDir::new().unwrap();
        let original_path = temp_dir.path().join("original");
        let checkpoint_path = temp_dir.path().join("checkpoint");

        // Create original store and add data
        {
            let cf_descriptor = ColumnFamilyDescriptor::new(TEST_CF, Options::default());
            let original_store = RocksDbStore::new(
                &original_path,
                vec![cf_descriptor],
                MetricsHelper::new(),
                &RocksDbConfig::default(),
            )
            .unwrap();

            original_store.put(TEST_CF, b"key1", b"value1").unwrap();
            original_store.put(TEST_CF, b"key2", b"value2").unwrap();

            // Create checkpoint
            original_store.create_checkpoint(&checkpoint_path).unwrap();
        } // Drop original store

        // Open new store from checkpoint
        let cf_descriptor = ColumnFamilyDescriptor::new(TEST_CF, Options::default());
        let recovered_store = RocksDbStore::new(
            &checkpoint_path,
            vec![cf_descriptor],
            MetricsHelper::new(),
            &RocksDbConfig::default(),
        )
        .unwrap();

        // Verify data is recovered
        let keys = vec![b"key1".as_slice(), b"key2".as_slice()];
        let results = recovered_store.multi_get(TEST_CF, keys).unwrap();

        assert_eq!(results.len(), 2);
        assert_eq!(results[0].as_ref().unwrap(), b"value1");
        assert_eq!(results[1].as_ref().unwrap(), b"value2");
    }

    #[test]
    fn test_get_sst_file_names() {
        let (store, _temp_dir) = create_test_store();

        // Add some data to create SST files
        store.put(TEST_CF, b"key1", b"value1").unwrap();
        store.put(TEST_CF, b"key2", b"value2").unwrap();

        // Force flush to create SST files
        store.flush_cf(TEST_CF).unwrap();

        // Get SST file names
        let sst_files = store.get_sst_file_names(TEST_CF).unwrap();

        // Should have at least one SST file after flush
        assert!(!sst_files.is_empty());

        // All file names should end with .sst
        for file_name in &sst_files {
            assert!(file_name.ends_with(".sst"));
        }
    }

    #[test]
    fn test_compute_sst_delta() {
        let old_files = vec![
            "000001.sst".to_string(),
            "000002.sst".to_string(),
            "000003.sst".to_string(),
        ];

        let new_files = vec![
            "000002.sst".to_string(), // unchanged
            "000003.sst".to_string(), // unchanged
            "000004.sst".to_string(), // added
            "000005.sst".to_string(), // added
        ];

        let delta = RocksDbStore::compute_sst_delta(&old_files, &new_files);

        assert_eq!(delta.added_files.len(), 2);
        assert!(delta.added_files.contains(&"000004.sst".to_string()));
        assert!(delta.added_files.contains(&"000005.sst".to_string()));

        assert_eq!(delta.removed_files.len(), 1);
        assert!(delta.removed_files.contains(&"000001.sst".to_string()));

        assert_eq!(delta.unchanged_files.len(), 2);
        assert!(delta.unchanged_files.contains(&"000002.sst".to_string()));
        assert!(delta.unchanged_files.contains(&"000003.sst".to_string()));
    }

    #[test]
    fn test_sst_delta_tracking_with_checkpoints() {
        let temp_dir = TempDir::new().unwrap();
        let db_path = temp_dir.path().join("db");
        let checkpoint1_path = temp_dir.path().join("checkpoint1");
        let checkpoint2_path = temp_dir.path().join("checkpoint2");

        let cf_descriptor = ColumnFamilyDescriptor::new(TEST_CF, Options::default());
        let store = RocksDbStore::new(
            &db_path,
            vec![cf_descriptor],
            MetricsHelper::new(),
            &RocksDbConfig::default(),
        )
        .unwrap();

        // Phase 1: Add initial data
        store.put(TEST_CF, b"key1", b"value1").unwrap();
        store.put(TEST_CF, b"key2", b"value2").unwrap();
        store.flush_cf(TEST_CF).unwrap();

        let sst_files_phase1 = store.get_sst_file_names(TEST_CF).unwrap();
        store.create_checkpoint(&checkpoint1_path).unwrap();

        // Phase 2: Add more data
        store.put(TEST_CF, b"key3", b"value3").unwrap();
        store.put(TEST_CF, b"key4", b"value4").unwrap();
        store.flush_cf(TEST_CF).unwrap();

        let sst_files_phase2 = store.get_sst_file_names(TEST_CF).unwrap();
        store.create_checkpoint(&checkpoint2_path).unwrap();

        // Compute delta between phases
        let delta = RocksDbStore::compute_sst_delta(&sst_files_phase1, &sst_files_phase2);

        // Should have some changes (either added files or unchanged files)
        // The exact number depends on compaction behavior, but total should be consistent
        let total_delta_files =
            delta.added_files.len() + delta.unchanged_files.len() + delta.removed_files.len();
        let total_phase2_files = sst_files_phase2.len();

        // Delta should account for all files in phase2 (either added or unchanged)
        assert!(total_delta_files >= total_phase2_files || sst_files_phase2.is_empty());
    }

    #[test]
    fn test_parse_compression_type_valid() {
        assert_eq!(
            parse_compression_type("none").unwrap(),
            DBCompressionType::None
        );
        assert_eq!(
            parse_compression_type("lz4").unwrap(),
            DBCompressionType::Lz4
        );
        assert_eq!(
            parse_compression_type("lz4hc").unwrap(),
            DBCompressionType::Lz4hc
        );
        assert_eq!(
            parse_compression_type("zstd").unwrap(),
            DBCompressionType::Zstd
        );
        assert_eq!(
            parse_compression_type("snappy").unwrap(),
            DBCompressionType::Snappy
        );
        assert_eq!(
            parse_compression_type("zlib").unwrap(),
            DBCompressionType::Zlib
        );
    }

    #[test]
    fn test_parse_compression_type_case_insensitive() {
        assert_eq!(
            parse_compression_type("LZ4").unwrap(),
            DBCompressionType::Lz4
        );
        assert_eq!(
            parse_compression_type("Zstd").unwrap(),
            DBCompressionType::Zstd
        );
        assert_eq!(
            parse_compression_type("  lz4  ").unwrap(),
            DBCompressionType::Lz4
        );
    }

    #[test]
    fn test_parse_compression_type_invalid() {
        assert!(parse_compression_type("brotli").is_err());
        assert!(parse_compression_type("").is_err());
    }

    #[test]
    fn test_parse_compression_per_level() {
        let levels = parse_compression_per_level("none,none,lz4,lz4,lz4,lz4,lz4").unwrap();
        assert_eq!(
            levels,
            vec![
                DBCompressionType::None,
                DBCompressionType::None,
                DBCompressionType::Lz4,
                DBCompressionType::Lz4,
                DBCompressionType::Lz4,
                DBCompressionType::Lz4,
                DBCompressionType::Lz4,
            ]
        );
    }

    #[test]
    fn test_parse_compression_per_level_mixed() {
        let levels = parse_compression_per_level("none,lz4,zstd").unwrap();
        assert_eq!(
            levels,
            vec![
                DBCompressionType::None,
                DBCompressionType::Lz4,
                DBCompressionType::Zstd,
            ]
        );
    }

    #[test]
    fn test_parse_compression_per_level_invalid_entry() {
        assert!(parse_compression_per_level("none,invalid,lz4").is_err());
    }
}
