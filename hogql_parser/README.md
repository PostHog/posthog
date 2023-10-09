# HogQL Parser

## Developing locally on macOS

1. Install libraries:

    ```bash
    brew install boost antlr
    ```

1. Install `hogql_parser` from local sources:

    ```bash
    pip install ./hogql_parser
    ```

1. If you now run tests, the locally-built version of `hogql_parser` will be used:

    ```bash
    pytest posthog/hogql/
    ```
