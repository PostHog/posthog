//! Pipeline-specific implementations for the deduplicator.
//!
//! # Architecture
//!
//! The kafka-deduplicator is designed to support multiple event types with
//! potentially different deduplication strategies. Each "pipeline" encapsulates
//! the complete logic for processing a specific event type from a Kafka topic.
//!
//! ## Why Pipelines?
//!
//! Different event types may require fundamentally different deduplication approaches:
//!
//! - **Ingestion events** use timestamp-based deduplication (timestamp + event + distinct_id + token)
//! - Future pipelines might use UUID-only deduplication, content hashing, or other strategies
//!
//! Rather than parameterizing a single processor with types, each pipeline owns its
//! complete processing logic. This allows pipelines to have entirely different:
//! - Deduplication key computation
//! - Similarity scoring algorithms
//! - Metadata storage formats
//! - Result types and error handling
//!
//! ## Traits vs Concrete Types
//!
//! The traits in [`traits`] define contracts that pipeline components implement:
//! - [`DeduplicationKeyExtractor`] - Extracts dedup keys from domain events
//! - [`EventParser`] - Transforms wire format to domain events
//! - [`DeduplicationMetadata`] - Manages metadata storage and similarity calculation
//!
//! These traits enable code reuse for shared infrastructure (stores, consumers)
//! while allowing pipeline-specific implementations. The traits are not used
//! polymorphically at runtime—they serve as compile-time contracts ensuring
//! pipelines implement the required interfaces.
//!
//! ## Adding a New Pipeline
//!
//! To add a new pipeline (e.g., for a different event type or topic):
//!
//! 1. Create a new submodule under `pipelines/`
//! 2. Implement the required traits for your event types
//! 3. Create a pipeline-specific processor implementing `BatchConsumerProcessor`
//! 4. Wire it into the service (currently compile-time selection)
//!
//! See [`ingestion_events`] for a complete implementation example.
//!
//! # Module Structure
//!
//! ```text
//! pipelines/
//! ├── traits.rs            # Core trait definitions
//! └── ingestion_events/
//!     ├── mod.rs           # Pipeline module root and exports
//!     ├── keys.rs          # DeduplicationKeyExtractor impl
//!     ├── parser.rs        # EventParser impl
//!     ├── metadata.rs      # DeduplicationMetadata impl
//!     ├── processor.rs     # Batch processor with dedup logic
//!     ├── dedup_result.rs  # Result types for this pipeline
//!     └── duplicate_event.rs # Duplicate event publishing format
//! ```

mod pipeline_builder;

pub mod clickhouse_events;
pub mod ingestion_events;
pub mod processor;
pub mod results;
pub mod timestamp_deduplicator;
pub mod traits;

pub use pipeline_builder::{PipelineBuilder, PipelineConsumer};

pub use processor::{
    batch_read_timestamp_records, batch_write_timestamp_records, emit_deduplication_result_metrics,
    get_result_labels, get_store_or_drop, DeduplicationResult, DeduplicationResultLabels,
    DuplicateInfo, DuplicateReason, StoreResult,
};
pub use results::{DedupFieldName, EnrichedEvent, EventSimilarity, PropertyDifference};
pub use timestamp_deduplicator::{
    DeduplicatableEvent, PublisherConfig, TimestampDeduplicator, TimestampDeduplicatorConfig,
};
pub use traits::{
    DeduplicationKeyExtractor, DeduplicationMetadata, EventParser, FailOpenProcessor,
};
