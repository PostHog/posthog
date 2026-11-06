use anyhow::Result;
use async_trait::async_trait;
use tokio_util::sync::CancellationToken;

use super::CheckpointPlan;

/// Trait for uploading checkpoints to remote storage
#[async_trait]
pub trait CheckpointUploader: Send + Sync + std::fmt::Debug {
    /// Upload checkpoint using a plan (specific files + metadata) - legacy non-cancellable
    async fn upload_checkpoint_with_plan(&self, plan: &CheckpointPlan) -> Result<Vec<String>> {
        self.upload_checkpoint_with_plan_cancellable(plan, None)
            .await
    }

    /// Upload checkpoint with cancellation support.
    /// If cancel_token is provided and cancelled during upload, returns an error early
    /// and aborts any in-progress multipart uploads to prevent ghost uploads.
    async fn upload_checkpoint_with_plan_cancellable(
        &self,
        plan: &CheckpointPlan,
        cancel_token: Option<&CancellationToken>,
    ) -> Result<Vec<String>>;

    /// Check if the uploader is available/configured
    async fn is_available(&self) -> bool;
}
