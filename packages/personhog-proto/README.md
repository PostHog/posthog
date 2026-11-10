# personhog-proto

Python bindings for the personhog protos (`ingestion/proto/personhog`), installed locally by `uv sync` and included in the application image.
The package exposes `personhog.*` because protoc derives Python imports from the paths in proto imports.
This keeps generated code usable without rewriting its imports.

The bindings are generated from the protos at the commit `PROTO_SOURCE.json` records, not from the working tree, so a proto change on ingestion's side does not change them until Django takes it. `bin/generate_personhog_proto.sh` regenerates from the pinned commit and CI checks the result matches; `bin/generate_personhog_proto.sh --bump` moves the pin to the current protos and regenerates, which is the PR that adopts a new API.
The `proto-codegen` dependency group pins the generator and formatter for development and CI.
