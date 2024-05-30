operations: list = [
    # this migration has been amended to be entirely No-op
    # it has applied successfully in Prod US where it was a no-op
    # as all tables/columns it affected already existed
    # it failed to apply in prod EU but there the change has been applied manually
    # keeping it here so that hopefully it applies in EU
    # and then EU and US migration listing are the same
    # and nobody re-uses the 0046 migration label
]
