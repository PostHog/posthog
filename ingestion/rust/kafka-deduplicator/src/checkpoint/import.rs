use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use super::error::{DownloadCancelledError, ImportTimeoutError};
use super::{CheckpointDownloader, CheckpointMetadata};
use crate::metrics_const::{
    CHECKPOINT_IMPORT_ATTEMPT_DURATION_HISTOGRAM, CHECKPOINT_IMPORT_DURATION_HISTOGRAM,
};

use anyhow::{Context, Result};
use tokio_util::sync::CancellationToken;
use tracing::{error, info, warn};

/// Cleanup guard that removes the import directory on drop unless defused.
/// Handles: failures, timeouts, cancellations, panics during import.
struct ImportCleanupGuard {
    path: PathBuf,
    topic: String,
    partition: i32,
    defused: bool,
}

impl ImportCleanupGuard {
    fn new(path: PathBuf, topic: String, partition: i32) -> Self {
        Self {
            path,
            topic,
            partition,
            defused: false,
        }
    }

    /// Defuse the guard - directory will NOT be cleaned up on drop.
    /// Call this when import succeeds and path should be kept.
    fn defuse(mut self) -> PathBuf {
        self.defused = true;
        std::mem::take(&mut self.path)
    }
}

impl Drop for ImportCleanupGuard {
    fn drop(&mut self) {
        if !self.defused && self.path.exists() {
            match std::fs::remove_dir_all(&self.path) {
                Ok(_) => {
                    info!(
                        topic = %self.topic,
                        partition = self.partition,
                        path = %self.path.display(),
                        "Import cleanup guard: removed incomplete import directory"
                    );
                }
                Err(e) => {
                    warn!(
                        topic = %self.topic,
                        partition = self.partition,
                        path = %self.path.display(),
                        error = ?e,
                        "Import cleanup guard: failed to remove directory, orphan cleaner will handle it"
                    );
                }
            }
        }
    }
}

#[derive(Debug)]
pub struct CheckpointImporter {
    downloader: Box<dyn CheckpointDownloader>,
    // Base path for local RocksDB stores - checkpoint files are downloaded directly here
    store_base_path: PathBuf,
    // Number of historical checkpoint attempts to import as fallbacks
    import_attempt_depth: usize,
    // Maximum time allowed for a complete checkpoint import operation
    import_timeout: Duration,
}

impl CheckpointImporter {
    pub fn new(
        downloader: Box<dyn CheckpointDownloader>,
        store_base_path: PathBuf,
        import_attempt_depth: usize,
        import_timeout: Duration,
    ) -> Self {
        Self {
            downloader,
            store_base_path,
            import_attempt_depth,
            import_timeout,
        }
    }

    /// Import checkpoint files directly into the store directory for a topic/partition.
    ///
    /// This method will:
    /// 1. List recent checkpoint metadata.json keys from remote storage for the topic+partition
    /// 2. For each key (newest to oldest, up to import_attempt_depth), lazily download the
    ///    metadata.json and attempt to download all tracked files to the partition store
    ///    directory: `<store_base_path>/<topic>/<partition>/`
    /// 3. If a checkpoint import fails, fall back to the next most recent
    /// 4. If successful, write metadata.json to that directory and return the store path
    ///
    /// Metadata files are downloaded lazily (one at a time, only when needed) rather than
    /// eagerly in bulk, to reduce S3 pressure during rebalances when many partitions import
    /// simultaneously.
    pub async fn import_checkpoint_for_topic_partition(
        &self,
        topic: &str,
        partition_number: i32,
    ) -> Result<PathBuf> {
        self.import_checkpoint_for_topic_partition_cancellable(topic, partition_number, None)
            .await
    }

    /// Import checkpoint files with optional cancellation support.
    /// If cancel_token is provided and cancelled during download, returns an error early.
    /// The import is wrapped with a timeout to prevent exceeding Kafka max poll interval.
    pub async fn import_checkpoint_for_topic_partition_cancellable(
        &self,
        topic: &str,
        partition_number: i32,
        cancel_token: Option<&CancellationToken>,
    ) -> Result<PathBuf> {
        let start_time = Instant::now();

        // Wrap the entire import with a timeout to prevent exceeding Kafka max poll interval
        match tokio::time::timeout(
            self.import_timeout,
            self.import_checkpoint_inner(topic, partition_number, cancel_token, start_time),
        )
        .await
        {
            Ok(result) => result,
            Err(_elapsed) => {
                error!(
                    topic = topic,
                    partition = partition_number,
                    timeout_secs = self.import_timeout.as_secs(),
                    elapsed_secs = start_time.elapsed().as_secs_f64(),
                    "Checkpoint import timed out"
                );
                metrics::histogram!(CHECKPOINT_IMPORT_DURATION_HISTOGRAM, "result" => "timeout")
                    .record(start_time.elapsed().as_secs_f64());
                Err(ImportTimeoutError {
                    topic: topic.to_string(),
                    partition: partition_number,
                    timeout_secs: self.import_timeout.as_secs(),
                }
                .into())
            }
        }
    }

    /// Inner implementation of checkpoint import, called with a timeout wrapper.
    ///
    /// Downloads metadata.json files lazily (one at a time) to avoid wasting S3 bandwidth
    /// on metadata we may never need. In the happy path only the newest metadata is fetched.
    async fn import_checkpoint_inner(
        &self,
        topic: &str,
        partition_number: i32,
        cancel_token: Option<&CancellationToken>,
        start_time: Instant,
    ) -> Result<PathBuf> {
        let metadata_keys = match self
            .downloader
            .list_recent_checkpoints(topic, partition_number)
            .await
        {
            Ok(keys) => keys,
            Err(e) => {
                metrics::histogram!(CHECKPOINT_IMPORT_DURATION_HISTOGRAM, "result" => "failed")
                    .record(start_time.elapsed().as_secs_f64());
                return Err(e).context("listing checkpoint metadata");
            }
        };

        if metadata_keys.is_empty() {
            metrics::histogram!(CHECKPOINT_IMPORT_DURATION_HISTOGRAM, "result" => "failed")
                .record(start_time.elapsed().as_secs_f64());
            return Err(anyhow::anyhow!(
                "No checkpoint metadata files found for topic:{topic} partition:{partition_number}"
            ));
        }

        // Truncate to import_attempt_depth BEFORE downloading any content
        let metadata_keys: Vec<_> = metadata_keys
            .into_iter()
            .take(self.import_attempt_depth)
            .collect();

        info!(
            "Found checkpoint metadata keys for topic:{topic} partition:{partition_number}, \
             will attempt up to {} (newest first)",
            metadata_keys.len(),
        );

        for remote_key in &metadata_keys {
            // Check cancellation before each attempt
            if let Some(token) = cancel_token {
                if token.is_cancelled() {
                    warn!(
                        topic = topic,
                        partition = partition_number,
                        "Checkpoint import cancelled before attempt"
                    );
                    metrics::histogram!(CHECKPOINT_IMPORT_DURATION_HISTOGRAM, "result" => "cancelled")
                        .record(start_time.elapsed().as_secs_f64());
                    return Err(DownloadCancelledError {
                        reason: "import cancelled before attempt".to_string(),
                    }
                    .into());
                }
            }

            let attempt_start = Instant::now();

            // Lazy download: only fetch this metadata.json when we actually need it,
            // avoiding unnecessary S3 GETs during rebalances
            let mut attempt = match self.downloader.download_file(remote_key).await {
                Ok(content) => match CheckpointMetadata::from_json_bytes(&content) {
                    Ok(metadata) => metadata,
                    Err(e) => {
                        error!("Failed to parse metadata: {remote_key}: {e:#}");
                        continue;
                    }
                },
                Err(e) => {
                    error!("Failed to download metadata: {remote_key}: {e:#}");
                    continue;
                }
            };

            let local_attempt_path = attempt.get_store_path(&self.store_base_path);
            let local_path_tag = local_attempt_path.to_string_lossy().to_string();
            let attempt_tag = attempt.get_attempt_path();

            // If a stale store directory exists, remove it before importing.
            // The caller already determined local data is stale or missing.
            if local_attempt_path.exists() {
                info!(
                    topic = topic,
                    partition = partition_number,
                    path = %local_attempt_path.display(),
                    "Removing stale local store before import"
                );
                let _ = tokio::fs::remove_dir_all(&local_attempt_path).await;
            }

            // Create the directory for this import attempt
            if let Err(e) = tokio::fs::create_dir_all(&local_attempt_path).await {
                metrics::histogram!(CHECKPOINT_IMPORT_ATTEMPT_DURATION_HISTOGRAM, "result" => "failed")
                    .record(attempt_start.elapsed().as_secs_f64());
                metrics::histogram!(CHECKPOINT_IMPORT_DURATION_HISTOGRAM, "result" => "failed")
                    .record(start_time.elapsed().as_secs_f64());
                return Err(e).with_context(|| {
                    format!(
                        "Failed to create local directory for import: {}",
                        local_path_tag
                    )
                });
            }

            // Guard cleans up directory on drop (failure/timeout/cancel/panic) unless defused (success)
            let guard = ImportCleanupGuard::new(
                local_attempt_path.clone(),
                topic.to_string(),
                partition_number,
            );

            // Create child token for this attempt - allows sibling download cancellation
            // on error while preserving fallback to next checkpoint attempt.
            // Child token is cancelled when parent is cancelled (rebalance), or when
            // a file download fails (sibling cancellation).
            let attempt_token = cancel_token
                .map(|parent| parent.child_token())
                .unwrap_or_default();

            match self
                .fetch_checkpoint_files_cancellable(
                    &attempt,
                    &local_attempt_path,
                    Some(&attempt_token),
                )
                .await
            {
                Ok(_) => {
                    let attempt_duration = attempt_start.elapsed().as_secs_f64();

                    // Persist metadata.json to the local store directory (write_to_dir stamps updated_at = Utc::now())
                    attempt
                        .write_to_dir(&local_attempt_path)
                        .await
                        .with_context(|| {
                            format!(
                                "Failed to write metadata.json to import dir: {}",
                                local_attempt_path.display()
                            )
                        })?;

                    info!(
                        checkpoint = attempt_tag,
                        local_store_path = local_path_tag,
                        original_checkpoint_timestamp = %attempt.attempt_timestamp,
                        attempt_duration_secs = attempt_duration,
                        total_duration_secs = start_time.elapsed().as_secs_f64(),
                        "Successfully imported checkpoint to local directory"
                    );
                    metrics::histogram!(CHECKPOINT_IMPORT_ATTEMPT_DURATION_HISTOGRAM, "result" => "success")
                        .record(attempt_duration);
                    metrics::histogram!(CHECKPOINT_IMPORT_DURATION_HISTOGRAM, "result" => "success")
                        .record(start_time.elapsed().as_secs_f64());

                    // Defuse guard - import succeeded, keep the directory
                    return Ok(guard.defuse());
                }
                Err(e) => {
                    // Guard drops here automatically, cleans up directory
                    let attempt_duration = attempt_start.elapsed().as_secs_f64();
                    metrics::histogram!(CHECKPOINT_IMPORT_ATTEMPT_DURATION_HISTOGRAM, "result" => "failed")
                        .record(attempt_duration);
                    error!(
                        checkpoint = attempt_tag,
                        local_attempt_path = local_path_tag,
                        attempt_duration_secs = attempt_duration,
                        error = ?e,
                        "Failed to import checkpoint files"
                    );
                    continue;
                }
            }
        }

        let err_msg = format!(
            "No usable checkpoints identified in recovery window for topic:{topic} partition:{partition_number}"
        );
        error!(err_msg);
        metrics::histogram!(CHECKPOINT_IMPORT_DURATION_HISTOGRAM, "result" => "failed")
            .record(start_time.elapsed().as_secs_f64());
        Err(anyhow::anyhow!(err_msg))
    }

    pub async fn fetch_checkpoint_files(
        &self,
        checkpoint_metadata: &CheckpointMetadata,
        local_attempt_path: &Path,
    ) -> Result<()> {
        self.fetch_checkpoint_files_cancellable(checkpoint_metadata, local_attempt_path, None)
            .await
    }

    pub async fn fetch_checkpoint_files_cancellable(
        &self,
        checkpoint_metadata: &CheckpointMetadata,
        local_attempt_path: &Path,
        cancel_token: Option<&CancellationToken>,
    ) -> Result<()> {
        let target_files = checkpoint_metadata
            .files
            .iter()
            .map(|f| f.remote_filepath.clone())
            .collect::<Vec<_>>();

        info!(
            metadata = checkpoint_metadata.get_metadata_filepath(),
            file_count = checkpoint_metadata.files.len(),
            "Fetching checkpoint files from metadata tracking list",
        );

        match self
            .downloader
            .download_files_cancellable(&target_files, local_attempt_path, cancel_token)
            .await
        {
            Ok(_) => {
                info!(
                    "Successfully downloaded {} checkpoint files to: {local_attempt_path:?}",
                    target_files.len()
                );
                Ok(())
            }
            Err(e) => {
                error!("Failed to download checkpoint files to: {local_attempt_path:?}: {e:#}");
                Err(e)
            }
        }
    }

    pub async fn is_available(&self) -> bool {
        self.downloader.is_available().await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use async_trait::async_trait;
    use chrono::{TimeZone, Utc};
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;
    use std::time::Duration;
    use tempfile::TempDir;

    /// Mock downloader for testing checkpoint import behavior
    #[derive(Debug)]
    struct MockDownloader {
        metadata: CheckpointMetadata,
        download_count: Arc<AtomicUsize>,
    }

    impl MockDownloader {
        fn new(metadata: CheckpointMetadata) -> Self {
            Self {
                metadata,
                download_count: Arc::new(AtomicUsize::new(0)),
            }
        }
    }

    #[async_trait]
    impl CheckpointDownloader for MockDownloader {
        async fn list_recent_checkpoints(
            &self,
            _topic: &str,
            _partition_number: i32,
        ) -> Result<Vec<String>> {
            Ok(vec![self.metadata.get_metadata_filepath()])
        }

        async fn download_file(&self, _remote_key: &str) -> Result<Vec<u8>> {
            let json = self.metadata.to_json()?;
            Ok(json.into_bytes())
        }

        async fn download_and_store_file_cancellable(
            &self,
            _remote_key: &str,
            local_filepath: &Path,
            cancel_token: Option<&CancellationToken>,
        ) -> Result<()> {
            if let Some(token) = cancel_token {
                if token.is_cancelled() {
                    return Err(DownloadCancelledError {
                        reason: "test mock".to_string(),
                    }
                    .into());
                }
            }
            tokio::fs::write(local_filepath, b"mock file content").await?;
            Ok(())
        }

        async fn download_files_cancellable(
            &self,
            remote_keys: &[String],
            local_base_path: &Path,
            cancel_token: Option<&CancellationToken>,
        ) -> Result<()> {
            self.download_count.fetch_add(1, Ordering::SeqCst);
            for key in remote_keys {
                let filename = key.rsplit('/').next().unwrap_or(key);
                let local_path = local_base_path.join(filename);
                self.download_and_store_file_cancellable(key, &local_path, cancel_token)
                    .await?;
            }
            Ok(())
        }

        async fn is_available(&self) -> bool {
            true
        }
    }

    /// Mock downloader for testing pre-cancellation checks.
    /// For more complex cancellation scenarios (sibling cancellation, fallback),
    /// use MinIO integration tests which exercise the real S3Downloader.
    #[derive(Debug)]
    struct CancellationTestDownloader {
        checkpoints: Vec<CheckpointMetadata>,
    }

    impl CancellationTestDownloader {
        fn new(checkpoints: Vec<CheckpointMetadata>) -> Self {
            Self { checkpoints }
        }
    }

    // NOTE: This mock uses sequential downloads and does NOT implement sibling cancellation
    // (no FuturesUnordered, no token.cancel() on error). It is suitable only for testing
    // pre-cancellation paths. Complex cancellation scenarios (sibling cancellation,
    // fallback after attempt failure) are tested in checkpoint_integration_tests.rs
    // using real S3Downloader with MinIO.
    #[async_trait]
    impl CheckpointDownloader for CancellationTestDownloader {
        async fn list_recent_checkpoints(
            &self,
            _topic: &str,
            _partition_number: i32,
        ) -> Result<Vec<String>> {
            Ok(self
                .checkpoints
                .iter()
                .map(|m| m.get_metadata_filepath())
                .collect())
        }

        async fn download_file(&self, remote_key: &str) -> Result<Vec<u8>> {
            // Find the matching checkpoint metadata
            for checkpoint in &self.checkpoints {
                if checkpoint.get_metadata_filepath() == remote_key {
                    return Ok(checkpoint.to_json()?.into_bytes());
                }
            }
            Err(anyhow::anyhow!("Metadata not found: {remote_key}"))
        }

        async fn download_and_store_file_cancellable(
            &self,
            _remote_key: &str,
            local_filepath: &Path,
            cancel_token: Option<&CancellationToken>,
        ) -> Result<()> {
            // Check cancellation before starting
            if let Some(token) = cancel_token {
                if token.is_cancelled() {
                    return Err(DownloadCancelledError {
                        reason: "test mock".to_string(),
                    }
                    .into());
                }
            }

            tokio::fs::write(local_filepath, b"mock file content").await?;
            Ok(())
        }

        async fn download_files_cancellable(
            &self,
            remote_keys: &[String],
            local_base_path: &Path,
            cancel_token: Option<&CancellationToken>,
        ) -> Result<()> {
            // Check cancellation before starting
            if let Some(token) = cancel_token {
                if token.is_cancelled() {
                    return Err(DownloadCancelledError {
                        reason: "test mock".to_string(),
                    }
                    .into());
                }
            }

            for key in remote_keys {
                let filename = key.rsplit('/').next().unwrap_or(key);
                let local_path = local_base_path.join(filename);
                self.download_and_store_file_cancellable(key, &local_path, cancel_token)
                    .await?;
            }
            Ok(())
        }

        async fn is_available(&self) -> bool {
            true
        }
    }

    fn create_test_metadata(topic: &str, partition: i32, hour: u32) -> CheckpointMetadata {
        let timestamp = Utc.with_ymd_and_hms(2025, 6, 15, hour, 0, 0).unwrap();
        let mut metadata =
            CheckpointMetadata::new(topic.to_string(), partition, timestamp, 12345, 100, 50);
        metadata.track_file(
            format!("checkpoints/{topic}/{partition}/2025-06-15T{hour:02}-00-00Z/000001.sst",),
            "checksum1".to_string(),
        );
        metadata
    }

    #[tokio::test]
    async fn test_download_files_cancellable_returns_early_when_pre_cancelled() {
        let tmp_dir = TempDir::new().unwrap();
        let metadata = create_test_metadata("test-topic", 0, 12);
        let downloader = CancellationTestDownloader::new(vec![metadata]);

        // Create a pre-cancelled token
        let token = CancellationToken::new();
        token.cancel();

        let result = downloader
            .download_files_cancellable(
                &["checkpoints/test-topic/0/file.sst".to_string()],
                tmp_dir.path(),
                Some(&token),
            )
            .await;

        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(
            err.downcast_ref::<DownloadCancelledError>().is_some(),
            "Error should be DownloadCancelledError: {}",
            err
        );
    }

    #[tokio::test]
    async fn test_import_checkpoint_cancellable_returns_early_when_pre_cancelled() {
        let tmp_dir = TempDir::new().unwrap();
        let metadata = create_test_metadata("test-topic", 0, 12);
        let downloader = CancellationTestDownloader::new(vec![metadata]);
        let importer = CheckpointImporter::new(
            Box::new(downloader),
            tmp_dir.path().to_path_buf(),
            3,
            Duration::from_secs(60),
        );

        // Create a pre-cancelled token
        let token = CancellationToken::new();
        token.cancel();

        let result = importer
            .import_checkpoint_for_topic_partition_cancellable("test-topic", 0, Some(&token))
            .await;

        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(
            err.downcast_ref::<DownloadCancelledError>().is_some(),
            "Error should be DownloadCancelledError: {}",
            err
        );
    }

    #[tokio::test]
    async fn test_import_creates_timestamped_directory_with_marker() {
        let tmp_dir = TempDir::new().unwrap();
        let store_base_path = tmp_dir.path().to_path_buf();

        let topic = "test-topic";
        let partition = 0;
        // Use a fixed timestamp for the checkpoint metadata (this is the "old" checkpoint timestamp)
        let attempt_timestamp = Utc.with_ymd_and_hms(2025, 6, 15, 12, 0, 0).unwrap();

        let mut metadata = CheckpointMetadata::new(
            topic.to_string(),
            partition,
            attempt_timestamp,
            12345,
            100,
            50,
        );
        metadata.track_file(
            "checkpoints/test-topic/0/2025-06-15T12-00-00Z/000001.sst".to_string(),
            "checksum1".to_string(),
        );

        // Create importer with mock downloader
        let downloader = MockDownloader::new(metadata);
        let importer = CheckpointImporter::new(
            Box::new(downloader),
            store_base_path.clone(),
            3,
            Duration::from_secs(60),
        );

        // Record time bounds around the import
        let before_import = Utc::now();
        let result = importer
            .import_checkpoint_for_topic_partition(topic, partition)
            .await;
        let after_import = Utc::now();

        assert!(result.is_ok(), "Import should succeed: {:?}", result.err());
        let import_path = result.unwrap();
        assert!(import_path.exists(), "Import path should exist");

        // Verify the import path is <base>/<topic>/<partition>
        let expected_path = store_base_path.join(topic).join(partition.to_string());
        assert_eq!(
            import_path, expected_path,
            "Import path should be <base>/<topic>/<partition>"
        );

        // Verify the imported SST file exists
        let imported_file = import_path.join("000001.sst");
        assert!(
            imported_file.exists(),
            "Imported SST file should exist after successful import"
        );

        // Verify metadata.json exists and round-trips with correct topic/partition and updated_at
        let loaded_metadata = CheckpointMetadata::load_from_dir(&import_path)
            .await
            .expect("metadata.json should exist and deserialize");
        assert_eq!(loaded_metadata.topic, topic);
        assert_eq!(loaded_metadata.partition, partition);
        assert!(
            loaded_metadata.updated_at.timestamp_millis() >= before_import.timestamp_millis(),
            "updated_at should be >= before_import"
        );
        assert!(
            loaded_metadata.updated_at.timestamp_millis() <= after_import.timestamp_millis(),
            "updated_at should be <= after_import"
        );
    }

    /// Mock downloader that always fails during file download
    #[derive(Debug)]
    struct FailingDownloader {
        metadata: CheckpointMetadata,
    }

    impl FailingDownloader {
        fn new(metadata: CheckpointMetadata) -> Self {
            Self { metadata }
        }
    }

    #[async_trait]
    impl CheckpointDownloader for FailingDownloader {
        async fn list_recent_checkpoints(
            &self,
            _topic: &str,
            _partition_number: i32,
        ) -> Result<Vec<String>> {
            Ok(vec![self.metadata.get_metadata_filepath()])
        }

        async fn download_file(&self, _remote_key: &str) -> Result<Vec<u8>> {
            let json = self.metadata.to_json()?;
            Ok(json.into_bytes())
        }

        async fn download_and_store_file_cancellable(
            &self,
            _remote_key: &str,
            _local_filepath: &Path,
            _cancel_token: Option<&CancellationToken>,
        ) -> Result<()> {
            Err(anyhow::anyhow!("Simulated download failure"))
        }

        async fn download_files_cancellable(
            &self,
            _remote_keys: &[String],
            _local_base_path: &Path,
            _cancel_token: Option<&CancellationToken>,
        ) -> Result<()> {
            Err(anyhow::anyhow!("Simulated download failure"))
        }

        async fn is_available(&self) -> bool {
            true
        }
    }

    #[tokio::test]
    async fn test_cleanup_guard_removes_directory_on_failure() {
        let tmp_dir = TempDir::new().unwrap();
        let store_base_path = tmp_dir.path().to_path_buf();

        let topic = "test-topic";
        let partition = 0;
        let attempt_timestamp = Utc.with_ymd_and_hms(2025, 6, 15, 12, 0, 0).unwrap();

        let mut metadata = CheckpointMetadata::new(
            topic.to_string(),
            partition,
            attempt_timestamp,
            12345,
            100,
            50,
        );
        metadata.track_file(
            "checkpoints/test-topic/0/2025-06-15T12-00-00Z/000001.sst".to_string(),
            "checksum1".to_string(),
        );

        // Create importer with failing downloader
        let downloader = FailingDownloader::new(metadata);
        let importer = CheckpointImporter::new(
            Box::new(downloader),
            store_base_path.clone(),
            1, // Only 1 attempt so we fail fast
            Duration::from_secs(60),
        );

        // Record the store path
        let store_path = store_base_path.join(topic).join(partition.to_string());

        // Import should fail
        let result = importer
            .import_checkpoint_for_topic_partition(topic, partition)
            .await;
        assert!(result.is_err(), "Import should fail");

        // The cleanup guard should have removed the store directory
        assert!(
            !store_path.exists(),
            "Cleanup guard should have removed the store directory on failure"
        );
    }

    #[test]
    fn test_cleanup_guard_defuse_prevents_cleanup() {
        let tmp_dir = TempDir::new().unwrap();
        let test_path = tmp_dir.path().join("test_dir");
        std::fs::create_dir_all(&test_path).unwrap();
        let test_file = test_path.join("test_file.txt");
        std::fs::write(&test_file, b"test content").unwrap();

        // Create guard and defuse it
        let guard = ImportCleanupGuard::new(test_path.clone(), "topic".to_string(), 0);
        let returned_path = guard.defuse();

        // Path should be returned
        assert_eq!(returned_path, test_path);

        // Directory should still exist (guard was defused)
        assert!(test_path.exists(), "Directory should exist after defuse");
        assert!(test_file.exists(), "File should exist after defuse");
    }

    #[test]
    fn test_cleanup_guard_removes_directory_on_drop() {
        let tmp_dir = TempDir::new().unwrap();
        let test_path = tmp_dir.path().join("test_dir");
        std::fs::create_dir_all(&test_path).unwrap();
        let test_file = test_path.join("test_file.txt");
        std::fs::write(&test_file, b"test content").unwrap();

        // Create guard and let it drop without defusing
        {
            let _guard = ImportCleanupGuard::new(test_path.clone(), "topic".to_string(), 0);
            // guard drops here
        }

        // Directory should be removed
        assert!(
            !test_path.exists(),
            "Directory should be removed after guard drops"
        );
    }

    /// Parameterized mock downloader that tracks call counts and optionally
    /// injects file-download failures to exercise fallback logic.
    #[derive(Debug)]
    struct TrackingDownloader {
        checkpoints: Vec<CheckpointMetadata>,
        metadata_download_count: Arc<AtomicUsize>,
        /// Number of initial file-download attempts that should fail (0 = all succeed)
        file_download_fail_count: usize,
        file_download_attempts: Arc<AtomicUsize>,
    }

    impl TrackingDownloader {
        fn new(checkpoints: Vec<CheckpointMetadata>, file_download_fail_count: usize) -> Self {
            Self {
                checkpoints,
                metadata_download_count: Arc::new(AtomicUsize::new(0)),
                file_download_fail_count,
                file_download_attempts: Arc::new(AtomicUsize::new(0)),
            }
        }
    }

    #[async_trait]
    impl CheckpointDownloader for TrackingDownloader {
        async fn list_recent_checkpoints(
            &self,
            _topic: &str,
            _partition_number: i32,
        ) -> Result<Vec<String>> {
            Ok(self
                .checkpoints
                .iter()
                .map(|m| m.get_metadata_filepath())
                .collect())
        }

        async fn download_file(&self, remote_key: &str) -> Result<Vec<u8>> {
            self.metadata_download_count.fetch_add(1, Ordering::SeqCst);
            for checkpoint in &self.checkpoints {
                if checkpoint.get_metadata_filepath() == remote_key {
                    return Ok(checkpoint.to_json()?.into_bytes());
                }
            }
            Err(anyhow::anyhow!("Metadata not found: {remote_key}"))
        }

        async fn download_and_store_file_cancellable(
            &self,
            _remote_key: &str,
            local_filepath: &Path,
            _cancel_token: Option<&CancellationToken>,
        ) -> Result<()> {
            tokio::fs::write(local_filepath, b"mock file content").await?;
            Ok(())
        }

        async fn download_files_cancellable(
            &self,
            remote_keys: &[String],
            local_base_path: &Path,
            cancel_token: Option<&CancellationToken>,
        ) -> Result<()> {
            let attempt = self.file_download_attempts.fetch_add(1, Ordering::SeqCst);
            if attempt < self.file_download_fail_count {
                return Err(anyhow::anyhow!("Simulated file download failure"));
            }
            for key in remote_keys {
                let filename = key.rsplit('/').next().unwrap_or(key);
                let local_path = local_base_path.join(filename);
                self.download_and_store_file_cancellable(key, &local_path, cancel_token)
                    .await?;
            }
            Ok(())
        }

        async fn is_available(&self) -> bool {
            true
        }
    }

    #[tokio::test]
    async fn test_lazy_metadata_download_only_fetches_needed() {
        let tmp_dir = TempDir::new().unwrap();

        // 3 checkpoints available, newest first (hours 14, 13, 12)
        let checkpoints = vec![
            create_test_metadata("test-topic", 0, 14),
            create_test_metadata("test-topic", 0, 13),
            create_test_metadata("test-topic", 0, 12),
        ];

        let tracker = TrackingDownloader::new(checkpoints, 0);
        let download_count = Arc::clone(&tracker.metadata_download_count);

        let importer = CheckpointImporter::new(
            Box::new(tracker),
            tmp_dir.path().to_path_buf(),
            3,
            Duration::from_secs(60),
        );

        let result = importer
            .import_checkpoint_for_topic_partition("test-topic", 0)
            .await;

        assert!(result.is_ok(), "Import should succeed: {:?}", result.err());
        assert_eq!(
            download_count.load(Ordering::SeqCst),
            1,
            "Only the newest metadata.json should be downloaded when first attempt succeeds"
        );
    }

    #[tokio::test]
    async fn test_lazy_metadata_download_fallback_downloads_incrementally() {
        let tmp_dir = TempDir::new().unwrap();

        // 3 checkpoints, first 2 will fail file download, 3rd succeeds
        let checkpoints = vec![
            create_test_metadata("test-topic", 0, 14),
            create_test_metadata("test-topic", 0, 13),
            create_test_metadata("test-topic", 0, 12),
        ];

        let tracker = TrackingDownloader::new(checkpoints, 2);
        let metadata_count = Arc::clone(&tracker.metadata_download_count);

        let importer = CheckpointImporter::new(
            Box::new(tracker),
            tmp_dir.path().to_path_buf(),
            3,
            Duration::from_secs(60),
        );

        let result = importer
            .import_checkpoint_for_topic_partition("test-topic", 0)
            .await;

        assert!(
            result.is_ok(),
            "Import should succeed on 3rd attempt: {:?}",
            result.err()
        );
        assert_eq!(
            metadata_count.load(Ordering::SeqCst),
            3,
            "Should download exactly 3 metadata files (2 failed attempts + 1 success)"
        );
    }
}
