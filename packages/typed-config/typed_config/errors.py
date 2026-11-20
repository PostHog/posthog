class UndecryptedConfigError(ValueError):
    """Raised when a config value reaches conversion still Fernet-encrypted.

    Upstream decryption of the stored job inputs failed (e.g. the key that wrote them is no
    longer in the keychain), so the raw token would otherwise crash the field converter with an
    opaque, secret-leaking error such as ``invalid literal for int() with base 10: 'gAAAAA...'``.
    """


class ConfigValueError(ValueError):
    """Raised when a config field's value can't be converted to its declared type.

    A converter (e.g. ``int``) failing on user-supplied input would otherwise crash with an
    opaque, value-leaking builtin error such as ``invalid literal for int() with base 10: 'lakjsd'``.
    We name the field but never its value, so nothing a user typed reaches logs or error tracking.
    """
