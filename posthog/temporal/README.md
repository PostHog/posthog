# Temporal Workflows

This python package contains the Temporal Workflows we use for e.g. maintenance
tasks for the Person on Events project, and the Batch Export functionality.

TODO: It's currently a package under the Django project. However, the nature of
the Batch Exports functionality is that we are adding lots of dependencies that
are almost entirely unrelated to the web app. To avoid increased docker image
size, unnecessary pod churn on deployments, slow pip installs, slow IDE
performance, slow tooling performance it would be preferable to reduce the
interface between the web app and the temporal workers to the gRPC interface
rather than a Python object interface.

## Running locally

The easiest way to get this to work locally is by running `mprocs`. You'll be missing some environment variables to make sure Temporal can properly connect with the S3/Airbyte instances we use to run the jobs locally. Reach out to `#team-data-warehouse` in Slack to get those creds, add them to `.env`, and you're good to go.

## UI

You can access Temporal's UI at http://localhost:8081
