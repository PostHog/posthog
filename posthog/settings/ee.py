EE_AVAILABLE = False

try:
    from ee.apps import EnterpriseConfig  # noqa: F401
except ImportError:
    pass
else:
    EE_AVAILABLE = True
