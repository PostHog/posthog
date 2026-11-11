# @posthog/replay-storage

Session replay's storage library: the keystore and crypto, the session metadata and feature stores, the outputs and the configuration that the replay ingestion pipeline (the writer, in `@posthog/ingestion`) and the recording API (the reader, in `nodejs`) share. A change here must reach both at once, which is why both consume it by workspace path.
