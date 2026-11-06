//! Query tags for statements built at runtime, in the SQLCommenter shape pganalyze
//! and pgcollector both parse. The comment goes in front because
//! `pg_stat_activity.query` is cut at `track_activity_query_size`.

/// A quote or `*/` in a value would end the comment early, so any character outside
/// the identifier set becomes `_`; the tag stays a comment whatever it is given.
pub fn tagged(service: &str, operation: &str, sql: &str) -> String {
    let clean = |v: &str| -> String {
        v.chars()
            .map(|c| {
                if c.is_ascii_alphanumeric() || matches!(c, '_' | '-' | '.' | '/' | ':') {
                    c
                } else {
                    '_'
                }
            })
            .collect()
    };
    format!(
        "/* service='{}', operation='{}' */ {sql}",
        clean(service),
        clean(operation)
    )
}

/// `query_tag!("merge_flip_lock_persons", sql)`; `service` is the calling crate's name.
#[macro_export]
macro_rules! query_tag {
    ($operation:literal, $sql:expr) => {
        $crate::query_tags::tagged(env!("CARGO_PKG_NAME"), $operation, &$sql)
    };
}

#[cfg(test)]
mod tests {
    #[test]
    fn the_prefix_names_the_calling_crate() {
        assert_eq!(
            crate::query_tag!("warm_pool", "SELECT 1"),
            "/* service='personhog-common', operation='warm_pool' */ SELECT 1"
        );
        let sql = String::from("SELECT 2");
        assert!(crate::query_tag!("x", sql).ends_with("SELECT 2"));
        assert_eq!(
            super::tagged("svc", "a*/ DROP TABLE t; --", "SELECT 3"),
            "/* service='svc', operation='a_/_DROP_TABLE_t__--' */ SELECT 3"
        );
    }
}
