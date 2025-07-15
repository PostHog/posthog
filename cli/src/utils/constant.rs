pub const CODE_SNIPPET_TEMPLATE: &str = r#"!function(){try{var e="undefined"!=typeof window?window:"undefined"!=typeof global?global:"undefined"!=typeof globalThis?globalThis:"undefined"!=typeof self?self:{},n=(new e.Error).stack;n&&(e._posthogChunkIds=e._posthogChunkIds||{},e._posthogChunkIds[n]="__POSTHOG_CHUNK_ID__")}catch(e){}}();"#;
pub const CHUNKID_COMMENT_PREFIX: &str = "\n//# chunkId=__POSTHOG_CHUNK_ID__";
pub const CHUNKID_PLACEHOLDER: &str = "__POSTHOG_CHUNK_ID__";
