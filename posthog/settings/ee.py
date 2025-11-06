EE_AVAILABLE = False

try:
    from products.enterprise.backend.apps import EnterpriseConfig  # noqa: F401
except ImportError:
    pass
else:
    EE_AVAILABLE = True
