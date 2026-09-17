database "posthog" {
  table "writable_metrics2" {
    extend = "_metrics2_columns"
    engine "distributed" {
      cluster_name = "logs"
      remote_database = "posthog"
      remote_table = "metrics2"
    }
  }
  table "writable_metric_series2" {
    extend = "_metric_series2_columns"
    engine "distributed" {
      cluster_name = "logs"
      remote_database = "posthog"
      remote_table = "metric_series2"
    }
  }
  table "writable_metric_attributes2" {
    extend = "_metric_attributes2_columns"
    engine "distributed" {
      cluster_name = "logs"
      remote_database = "posthog"
      remote_table = "metric_attributes2"
    }
  }
  table "writable_metric_series3" {
    extend = "_metric_series3_columns"
    engine "distributed" {
      cluster_name = "logs"
      remote_database = "posthog"
      remote_table = "metric_series3"
    }
  }
  table "writable_metric_attributes3" {
    extend = "_metric_attributes3_columns"
    engine "distributed" {
      cluster_name = "logs"
      remote_database = "posthog"
      remote_table = "metric_attributes3"
    }
  }
  table "writable_metric_names3" {
    extend = "_metric_names3_columns"
    engine "distributed" {
      cluster_name = "logs"
      remote_database = "posthog"
      remote_table = "metric_names3"
    }
  }
  patch_materialized_view "metrics2_input_to_metrics" {
    to_table = "posthog.writable_metrics2"
  }
  patch_materialized_view "metrics2_input_to_metric_series" {
    to_table = "posthog.writable_metric_series2"
  }
  patch_materialized_view "metrics2_input_to_metric_attributes" {
    to_table = "posthog.writable_metric_attributes2"
  }
  patch_materialized_view "metrics2_input_to_resource_attributes" {
    to_table = "posthog.writable_metric_attributes2"
  }
  patch_materialized_view "metrics2_input_to_metric_names3" {
    to_table = "posthog.writable_metric_names3"
  }
  patch_materialized_view "metrics2_input_to_metric_series3" {
    to_table = "posthog.writable_metric_series3"
  }
  patch_materialized_view "metrics2_input_to_metric_attributes3" {
    to_table = "posthog.writable_metric_attributes3"
  }
  patch_materialized_view "metrics2_input_to_resource_attributes3" {
    to_table = "posthog.writable_metric_attributes3"
  }
}
