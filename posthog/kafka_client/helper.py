"""Helper for SSL-certificate-based Kafka auth (self-hosted deployments).

Originally for Heroku-style base64-encoded certificates
(https://github.com/heroku/kafka-helper). Only `ssl_cert_config` is called —
`_KafkaProducer` merges it into its confluent config when `KAFKA_BASE64_KEYS`
is true.
"""

import os
import atexit
import base64
from tempfile import NamedTemporaryFile

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization


def _cleanup_ssl_files():
    """Clean up SSL files on process exit."""
    global _ssl_files
    if _ssl_files is not None:
        cert_file, key_file, ca_file = _ssl_files
        for f in (cert_file, key_file, ca_file):
            try:
                f.close()
                os.unlink(f.name)
            except (OSError, FileNotFoundError):
                pass
        _ssl_files = None


def _write_ssl_files_for_confluent():
    """
    Write SSL certificate files for confluent-kafka and return the file paths.
    confluent-kafka requires file paths rather than SSL contexts.

    Returns a tuple of (cert_path, key_path, ca_path) as temporary file paths.
    Files are created with delete=False but cleaned up via atexit handler.
    """
    cert_file = NamedTemporaryFile(suffix=".crt", delete=False, mode="wb")
    key_file = NamedTemporaryFile(suffix=".key", delete=False, mode="wb")
    ca_file = NamedTemporaryFile(suffix=".crt", delete=False, mode="wb")

    # Set restrictive permissions on the key file (owner read/write only)
    os.chmod(key_file.name, 0o600)

    cert_file.write(base64.b64decode(os.environ["KAFKA_CLIENT_CERT_B64"].encode("utf-8")))
    cert_file.flush()

    # Write the private key (unencrypted for confluent-kafka)
    private_key = serialization.load_pem_private_key(
        base64.b64decode(os.environ["KAFKA_CLIENT_CERT_KEY_B64"].encode("utf-8")),
        password=None,
        backend=default_backend(),
    )
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_file.write(pem)
    key_file.flush()

    ca_file.write(base64.b64decode(os.environ["KAFKA_TRUSTED_CERT_B64"].encode("utf-8")))
    ca_file.flush()

    # Register cleanup handler
    atexit.register(_cleanup_ssl_files)

    return cert_file, key_file, ca_file


# Module-level storage for SSL files to keep them alive
_ssl_files: tuple | None = None


def ssl_cert_config() -> dict[str, str]:
    """Return the confluent-kafka SSL-cert config block for base64-keys mode.

    Writes the cert/key/CA files on first call and reuses the paths thereafter.
    Hostname verification is disabled to match the legacy kafka-python behavior.
    """
    global _ssl_files

    if _ssl_files is None:
        _ssl_files = _write_ssl_files_for_confluent()

    cert_file, key_file, ca_file = _ssl_files
    return {
        "security.protocol": "SSL",
        "ssl.certificate.location": cert_file.name,
        "ssl.key.location": key_file.name,
        "ssl.ca.location": ca_file.name,
        "ssl.endpoint.identification.algorithm": "none",
    }
