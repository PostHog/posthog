CREATE TABLE IF NOT EXISTS error_tracking_fingerprint_issue_state 
(
    team_id Int64,
    fingerprint VARCHAR,
    issue_id UUID,
    issue_name Nullable(VARCHAR),
    issue_description Nullable(VARCHAR),
    issue_status VARCHAR,
    assigned_user_id Nullable(Int64),
    assigned_role_id Nullable(UUID),
    first_seen DateTime64(3, 'UTC'),
    is_deleted Int8,
    version Int64
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

) ENGINE = Distributed('aux', 'default', 'raw_error_tracking_fingerprint_issue_state')
