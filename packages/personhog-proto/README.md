# personhog-proto

Python bindings for `proto/personhog`, installed locally by `uv sync` and included in the application image.
The package exposes `personhog.*` because protoc derives Python imports from the paths in proto imports.
This keeps generated code usable without rewriting its imports.

Edit the proto definitions and run `bin/generate_personhog_proto.sh` to regenerate the checked-in bindings.
The `proto-codegen` dependency group pins the generator and formatter for development and CI.
