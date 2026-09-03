"""Evaluation-level clustering for AI observability.

Two-stage pipeline:
  Stage A (hourly): sample $ai_evaluation events per ClusteringJob, compose a short
  text representation, and enqueue embeddings via the shared document_embeddings Kafka topic.

  Stage B (daily): per ClusteringJob, fetch accumulated embeddings, cluster (HDBSCAN),
  label, compute operational + evaluation-specific aggregates, and emit $ai_evaluation_clusters events.

Deliberately exports nothing: `trace_clustering.metrics` imports `.constants` from here, so an
aggregator would make that a cycle through the workflow modules.
"""
