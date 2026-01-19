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
2. If you've made any changes to UDFs, when ready to deploy, increment the version in `posthog/udf_versioner.py` and run it
3. Overwrite `user_defined_function.xml` in the `posthog-cloud-infra` repo (us, eu, and dev) with `user_scripts/latest_user_defined_function.xml` and deploy it
   - Verify that CH knows about the UDF by running `SELECT aggregate_funnel_vXX()`. The error message is different for functions that CH doesn't know about, and for invalid arguments.

4. Land a version of the posthog repo with the updated `user_scripts` folder from the new branch (make sure this PR doesn't include changes to this file with the new version)
5. Run the `copy_udfs_to_clickhouse` action in the `posthog_cloud_infra` repo to deploy the `user_scripts` folder to clickhouse
   - Verify that the new UDF works, by adapting the version in a CH query for a funnel insight.

6. After that deploy goes out, it is safe to land and deploy the full changes to the `posthog` repo

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
