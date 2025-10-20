"""
Helper methods for creating the kafka-python KafkaProducer and KafkaConsumer objects.
https://github.com/heroku/kafka-helper
"""

import os
import ssl
import json
import base64
from base64 import standard_b64encode
from tempfile import NamedTemporaryFile

from django.conf import settings

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from kafka import KafkaConsumer, KafkaProducer


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
        passwd = standard_b64encode(os.urandom(33))
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


def get_kafka_producer(acks="all", value_serializer=lambda v: json.dumps(v).encode("utf-8"), **kwargs):
    """
    Return a KafkaProducer that uses the SSLContext created with create_ssl_context.
    """

    producer = KafkaProducer(
        bootstrap_servers=settings.KAFKA_HOSTS,
        security_protocol="SSL",
        ssl_context=get_kafka_ssl_context(),
        value_serializer=value_serializer,
        acks=acks,
        **kwargs,
    )

    return producer


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
