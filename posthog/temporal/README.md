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
