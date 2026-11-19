"""Dashboard loading behind the `dashboard-v2` flag, kept apart from the code every team runs.

The dashboard views keep thin, flag-gated entry points and call into these modules. Teams without the
flag never reach them. One module per concern; import the module you need rather than re-exporting here.
"""
