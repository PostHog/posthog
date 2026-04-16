"""Helper for creating a Kafka producer with SSL authentication.

Originally for Heroku-style base64-encoded certificates
(https://github.com/heroku/kafka-helper). Only `get_kafka_producer` is used —
selected by `_KafkaProducer` when `KAFKA_BASE64_KEYS` is true.
"""

import os
import atexit
import base64
from tempfile import NamedTemporaryFile

from django.conf import settings

from confluent_kafka import Producer as ConfluentProducer
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


def get_kafka_producer(retries: int = 5) -> ConfluentProducer:
    """
    Return a confluent-kafka Producer that uses SSL certificates from environment variables.
    """
    global _ssl_files

    # Write SSL files once and keep them around
    if _ssl_files is None:
        _ssl_files = _write_ssl_files_for_confluent()

    cert_file, key_file, ca_file = _ssl_files

    hosts = settings.KAFKA_HOSTS
    bootstrap_servers = ",".join(hosts) if isinstance(hosts, list) else hosts

    config = {
        "bootstrap.servers": bootstrap_servers,
        "security.protocol": "SSL",
        "ssl.certificate.location": cert_file.name,
        "ssl.key.location": key_file.name,
        "ssl.ca.location": ca_file.name,
        # Disable hostname verification (same as original)
        "ssl.endpoint.identification.algorithm": "none",
        # Wait for leader to acknowledge (matches kafka-python default)
        "acks": 1,
        # Retry configuration
        "message.send.max.retries": retries,
        "retry.backoff.ms": 100,
        # Connection management
        "connections.max.idle.ms": 60000,
        "reconnect.backoff.ms": 50,
        "reconnect.backoff.max.ms": 1000,
        # Timeouts
        "socket.timeout.ms": 60000,
        "request.timeout.ms": 30000,
        # Explicit API version to avoid slow auto-detection
        "api.version.request": True,
        "broker.version.fallback": "2.8.0",
        # Enable TCP keepalive
        "socket.keepalive.enable": True,
        # Delivery report callback will be called for all messages
        "delivery.report.only.error": False,
    }

    return ConfluentProducer(config)
