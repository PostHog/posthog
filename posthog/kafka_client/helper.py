"""
Helper methods for creating Kafka producer and consumer objects with SSL authentication.
Originally for Heroku-style base64-encoded certificates.
https://github.com/heroku/kafka-helper
"""

import os
import ssl
import json
import atexit
import base64
from tempfile import NamedTemporaryFile

from django.conf import settings

from confluent_kafka import Producer as ConfluentProducer
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from kafka import KafkaConsumer


def get_kafka_ssl_context():
    """
    Returns an SSL context based on the certificate information in the Kafka config vars.
    """
    # NOTE: We assume that Kafka environment variables are present. If using
    # Apache Kafka on Heroku, they will be available in your app configuration.
    #
    # 1. Write the PEM certificates necessary for connecting to the Kafka brokers to physical
    # files.  The broker connection SSL certs are passed in environment/config variables and
    # the python and ssl libraries require them in physical files.  The public keys are written
    # to short lived NamedTemporaryFile files; the client key is encrypted before writing to
    # the short lived NamedTemporaryFile
    #
    # 2. Create and return an SSLContext for connecting to the Kafka brokers referencing the
    # PEM certificates written above
    #

    # stash the kafka certs in named temporary files for loading into SSLContext.  Initialize the
    # SSLContext inside the with so when it goes out of scope the files are removed which has them
    # existing for the shortest amount of time.  As extra caution password
    # protect/encrypt the client key
    with (
        NamedTemporaryFile(suffix=".crt") as cert_file,
        NamedTemporaryFile(suffix=".key") as key_file,
        NamedTemporaryFile(suffix=".crt") as trust_file,
    ):
        cert_file.write(base64.b64decode(os.environ["KAFKA_CLIENT_CERT_B64"].encode("utf-8")))
        cert_file.flush()

        # setup cryptography to password encrypt/protect the client key so it's not in the clear on
        # the filesystem.  Use the generated password in the call to load_cert_chain
        passwd = base64.standard_b64encode(os.urandom(33))
        private_key = serialization.load_pem_private_key(
            base64.b64decode(os.environ["KAFKA_CLIENT_CERT_KEY_B64"].encode("utf-8")),
            password=None,
            backend=default_backend(),
        )
        pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.BestAvailableEncryption(passwd),
        )
        key_file.write(pem)
        key_file.flush()

        trust_file.write(base64.b64decode(os.environ["KAFKA_TRUSTED_CERT_B64"].encode("utf-8")))
        trust_file.flush()

        # create an SSLContext for passing into the kafka provider using the create_default_context
        # function which creates an SSLContext with protocol set to PROTOCOL_SSLv23, OP_NO_SSLv2,
        # and OP_NO_SSLv3 when purpose=SERVER_AUTH.
        ssl_context = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH, cafile=trust_file.name)
        ssl_context.load_cert_chain(cert_file.name, keyfile=key_file.name, password=passwd)

        # Intentionally disabling hostname checking.  The Kafka cluster runs in the cloud and Apache
        # Kafka on Heroku doesn't currently provide stable hostnames.  We're pinned to a specific certificate
        # for this connection even though the certificate doesn't include host information.  We rely
        # on the ca trust_cert for this purpose.
        ssl_context.check_hostname = False

    return ssl_context


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


def get_kafka_consumer(topic=None, value_deserializer=lambda v: json.loads(v.decode("utf-8")), **kwargs):
    """
    Return a KafkaConsumer that uses the SSLContext created with create_ssl_context.
    """

    # Create the KafkaConsumer connected to the specified brokers. Use the
    # SSLContext that is created with create_ssl_context.
    consumer = KafkaConsumer(
        bootstrap_servers=settings.KAFKA_HOSTS,
        security_protocol="SSL",
        ssl_context=get_kafka_ssl_context(),
        value_deserializer=value_deserializer,
        consumer_timeout_ms=5000 if (settings.DEBUG and not settings.TEST) else 305000,
        **kwargs,
    )

    if topic:
        consumer.subscribe([topic])

    return consumer
