use std::collections::HashMap;

/// Centralized metrics helper that provides consistent baseline labels
/// across all metrics in the deduplication system
#[derive(Debug, Clone, Default)]
pub struct MetricsHelper {
    baseline_labels: HashMap<String, String>,
}

impl MetricsHelper {
    /// Create a new metrics helper with baseline labels
    pub fn new() -> Self {
        Self::default()
    }

    /// Create a metrics helper with topic and partition labels
    pub fn with_partition(_topic: &str, _partition: i32) -> Self {
        let labels = HashMap::new();

        Self {
            baseline_labels: labels,
        }
    }

    /// Add an additional baseline label
    pub fn with_label(mut self, key: &str, value: &str) -> Self {
        self.baseline_labels
            .insert(key.to_string(), value.to_string());
        self
    }

    /// Record a counter metric with baseline labels
    pub fn counter(&self, name: &str) -> CounterHelper {
        CounterHelper {
            name: name.to_string(),
            baseline_labels: self.baseline_labels.clone(),
            additional_labels: HashMap::new(),
        }
    }

    /// Record a histogram metric with baseline labels
    pub fn histogram(&self, name: &str) -> HistogramHelper {
        HistogramHelper {
            name: name.to_string(),
            baseline_labels: self.baseline_labels.clone(),
            additional_labels: HashMap::new(),
        }
    }

    /// Record a gauge metric with baseline labels
    pub fn gauge(&self, name: &str) -> GaugeHelper {
        GaugeHelper {
            name: name.to_string(),
            baseline_labels: self.baseline_labels.clone(),
            additional_labels: HashMap::new(),
        }
    }
}

/// Helper for counter metrics
pub struct CounterHelper {
    name: String,
    baseline_labels: HashMap<String, String>,
    additional_labels: HashMap<String, String>,
}

impl CounterHelper {
    /// Add additional labels to this specific metric
    pub fn with_label(mut self, key: &str, value: &str) -> Self {
        self.additional_labels
            .insert(key.to_string(), value.to_string());
        self
    }

    /// Increment the counter
    pub fn increment(self, value: u64) {
        let mut all_labels = self.baseline_labels.clone();
        all_labels.extend(self.additional_labels);

        metrics::counter!(
            self.name,
            &all_labels.into_iter().collect::<Vec<(String, String)>>()
        )
        .increment(value);
    }
}

/// Helper for histogram metrics
pub struct HistogramHelper {
    name: String,
    baseline_labels: HashMap<String, String>,
    additional_labels: HashMap<String, String>,
}

impl HistogramHelper {
    /// Add additional labels to this specific metric
    pub fn with_label(mut self, key: &str, value: &str) -> Self {
        self.additional_labels
            .insert(key.to_string(), value.to_string());
        self
    }

    /// Record a value
    pub fn record(self, value: f64) {
        let mut all_labels = self.baseline_labels.clone();
        all_labels.extend(self.additional_labels);

        // Convert to the format expected by the metrics crate
        metrics::histogram!(
            self.name,
            &all_labels.into_iter().collect::<Vec<(String, String)>>()
        )
        .record(value);
    }
}

/// Helper for gauge metrics
pub struct GaugeHelper {
    name: String,
    baseline_labels: HashMap<String, String>,
    additional_labels: HashMap<String, String>,
}

impl GaugeHelper {
    /// Add additional labels to this specific metric
    pub fn with_label(mut self, key: &str, value: &str) -> Self {
        self.additional_labels
            .insert(key.to_string(), value.to_string());
        self
    }

    /// Set the gauge value
    pub fn set(self, value: f64) {
        let mut all_labels = self.baseline_labels.clone();
        all_labels.extend(self.additional_labels);

        // Convert to the format expected by the metrics crate
        metrics::gauge!(
            self.name,
            &all_labels.into_iter().collect::<Vec<(String, String)>>()
        )
        .set(value);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_metrics_helper_with_additional_label() {
        let helper = MetricsHelper::with_partition("test_topic", 0)
            .with_label("service", "kafka-deduplicator")
            .with_label("version", "1.0.0");

        assert_eq!(helper.baseline_labels.len(), 2);
        assert_eq!(
            helper.baseline_labels.get("service"),
            Some(&"kafka-deduplicator".to_string())
        );
        assert_eq!(
            helper.baseline_labels.get("version"),
            Some(&"1.0.0".to_string())
        );
    }

    #[test]
    fn test_counter_helper_with_labels() {
        let helper = MetricsHelper::with_partition("test_topic", 0);
        let counter = helper
            .counter("test_counter")
            .with_label("operation", "dedup");

        // This would normally emit the metric, but in tests we just verify structure
        assert_eq!(
            counter.additional_labels.get("operation"),
            Some(&"dedup".to_string())
        );
    }
}
