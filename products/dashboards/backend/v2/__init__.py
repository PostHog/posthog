"""Dashboard loading behind the `dashboard-v2` flag, kept apart from the code every team runs.

The dashboard views reach these modules through `facade/api.py`. Teams without the
flag never reach them. One module per concern; import the module you need rather than re-exporting here.
"""
