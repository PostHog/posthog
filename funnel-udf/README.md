# Funnel UDFs

## Development workflow

- Building the binaries:
  - Exit flox: `exit`
  - Switch to the subfolder: `cd funnel-udf`
  - Execute the build script: `./build.sh`
  - Restart the clickhouse docker container

## Deployment workflow

For revertible cloud deploys:

1. Develop using the binary files at the top level of `user_scripts` (see section above), with schema defined in `docker/clickhouse/user_defined_function.xml`
2. When ready to deploy, increment the version in `posthog/udf_versioner.py` and run it. This generates versioned binaries and `latest_user_defined_function.xml`
3. Land a PR with the updated `user_scripts` folder (binaries + XML). **Do not** include the `UDF_VERSION` bump in this PR — that goes in a separate PR (step 5)
4. The binaries should be automatically deployed to Clickhouse, you must verify this in metabase by running `SELECT aggregate_funnel_vXX()`. An "invalid arguments" error means the function is registered. An "unknown function" error means the deploy hasn't taken effect yet. **Make sure to do this for both EU and US**
5. Once the deploy is confirmed, land a separate PR that bumps `UDF_VERSION` in `posthog/udf_versioner.py` to the new version. This switches the posthog query builder to use the new UDF

## Design decisions

- We tried writing the UDFs in Python, but this cause ClickHouse nodes to crash as the garbage collector could not keep up. As such we're now writing the functions in Rust.
- We're using `cross-rs` to compile the binaries - it's a cross platfrom rust compiler.

## Troubleshooting

### Running `./build.sh` fails in flox environment

If you're using `flox` for development, you'll have to exit out of the environment first (nix os isn't supported).

```text
Error:
   0: could not determine os in target triplet
   1: unsupported os in target, abi: "1.82.0", system: "rustc"
```
