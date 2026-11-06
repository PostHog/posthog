use rdkafka::error::RDKafkaErrorCode;

/// Stable, low-cardinality snake_case tag for an RDKafkaErrorCode.
/// Usable anywhere -- producer, sink, handler, logging.
///
/// Deliberately a curated set rather than the full ~170-variant enum: every
/// producer that tags errors shares this vocabulary, so codes stay comparable
/// across metrics and unlisted ones collapse to `rdkafka_other` instead of
/// growing label cardinality unbounded. Add a code here when it starts
/// mattering and every caller gains it at once.
pub fn error_code_tag(code: RDKafkaErrorCode) -> &'static str {
    match code {
        RDKafkaErrorCode::QueueFull => "queue_full",
        RDKafkaErrorCode::MessageSizeTooLarge => "message_size_too_large",
        RDKafkaErrorCode::MessageTimedOut => "message_timed_out",
        RDKafkaErrorCode::UnknownTopicOrPartition => "unknown_topic_or_partition",
        RDKafkaErrorCode::TopicAuthorizationFailed => "topic_authorization_failed",
        RDKafkaErrorCode::ClusterAuthorizationFailed => "cluster_authorization_failed",
        RDKafkaErrorCode::InvalidMessage => "invalid_message",
        RDKafkaErrorCode::InvalidMessageSize => "invalid_message_size",
        RDKafkaErrorCode::NotLeaderForPartition => "not_leader_for_partition",
        RDKafkaErrorCode::RequestTimedOut => "request_timed_out",
        // Broker/idempotent-producer codes from delivery reports
        RDKafkaErrorCode::NotEnoughReplicas => "not_enough_replicas",
        RDKafkaErrorCode::NotEnoughReplicasAfterAppend => "not_enough_replicas_after_append",
        RDKafkaErrorCode::OperationNotAttempted => "operation_not_attempted",
        RDKafkaErrorCode::OutOfOrderSequenceNumber => "out_of_order_sequence_number",
        RDKafkaErrorCode::DuplicateSequenceNumber => "duplicate_sequence_number",
        RDKafkaErrorCode::NetworkException => "network_exception",
        RDKafkaErrorCode::CoordinatorLoadInProgress => "coordinator_load_in_progress",
        RDKafkaErrorCode::CoordinatorNotAvailable => "coordinator_not_available",
        // Transport/infra codes surfaced by ClientContext::error() callback
        RDKafkaErrorCode::BrokerTransportFailure => "broker_transport_failure",
        RDKafkaErrorCode::AllBrokersDown => "all_brokers_down",
        RDKafkaErrorCode::Resolve => "resolve",
        RDKafkaErrorCode::Authentication => "authentication",
        RDKafkaErrorCode::SaslAuthenticationFailed => "sasl_authentication_failed",
        _ => "rdkafka_other",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[rstest::rstest]
    #[case(RDKafkaErrorCode::QueueFull, "queue_full")]
    #[case(RDKafkaErrorCode::MessageSizeTooLarge, "message_size_too_large")]
    #[case(RDKafkaErrorCode::MessageTimedOut, "message_timed_out")]
    #[case(
        RDKafkaErrorCode::UnknownTopicOrPartition,
        "unknown_topic_or_partition"
    )]
    #[case(
        RDKafkaErrorCode::TopicAuthorizationFailed,
        "topic_authorization_failed"
    )]
    #[case(
        RDKafkaErrorCode::ClusterAuthorizationFailed,
        "cluster_authorization_failed"
    )]
    #[case(RDKafkaErrorCode::InvalidMessage, "invalid_message")]
    #[case(RDKafkaErrorCode::InvalidMessageSize, "invalid_message_size")]
    #[case(RDKafkaErrorCode::NotLeaderForPartition, "not_leader_for_partition")]
    #[case(RDKafkaErrorCode::RequestTimedOut, "request_timed_out")]
    #[case(RDKafkaErrorCode::NotEnoughReplicas, "not_enough_replicas")]
    #[case(
        RDKafkaErrorCode::NotEnoughReplicasAfterAppend,
        "not_enough_replicas_after_append"
    )]
    #[case(RDKafkaErrorCode::OperationNotAttempted, "operation_not_attempted")]
    #[case(
        RDKafkaErrorCode::OutOfOrderSequenceNumber,
        "out_of_order_sequence_number"
    )]
    #[case(RDKafkaErrorCode::DuplicateSequenceNumber, "duplicate_sequence_number")]
    #[case(RDKafkaErrorCode::NetworkException, "network_exception")]
    #[case(
        RDKafkaErrorCode::CoordinatorLoadInProgress,
        "coordinator_load_in_progress"
    )]
    #[case(RDKafkaErrorCode::CoordinatorNotAvailable, "coordinator_not_available")]
    #[case(RDKafkaErrorCode::BrokerTransportFailure, "broker_transport_failure")]
    #[case(RDKafkaErrorCode::AllBrokersDown, "all_brokers_down")]
    #[case(RDKafkaErrorCode::Resolve, "resolve")]
    #[case(RDKafkaErrorCode::Authentication, "authentication")]
    #[case(
        RDKafkaErrorCode::SaslAuthenticationFailed,
        "sasl_authentication_failed"
    )]
    fn error_code_tag_named_variants(#[case] code: RDKafkaErrorCode, #[case] expected: &str) {
        assert_eq!(error_code_tag(code), expected);
    }

    #[rstest::rstest]
    #[case(RDKafkaErrorCode::Unknown)]
    #[case(RDKafkaErrorCode::OffsetOutOfRange)]
    #[case(RDKafkaErrorCode::GroupAuthorizationFailed)]
    fn error_code_tag_unlisted_codes_fall_through(#[case] code: RDKafkaErrorCode) {
        assert_eq!(error_code_tag(code), "rdkafka_other");
    }
}
