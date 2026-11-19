import gc
import os
import ssl
import select
import signal
import socket
import tempfile
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from parameterized import parameterized
from redis import Redis, RedisCluster
from redis.cluster import ClusterNode, NodesManager
from redis.connection import SSLConnection
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
    RedisClusterException,
    RedisError,
)

from posthog import quota_redis


@override_settings(
    TEST=False,
    REDIS_URL="redis://shared.invalid:6379/0",
    QUOTA_LIMITING_REDIS_URL="rediss://billing.invalid:6379/0",
    QUOTA_LIMITING_REDIS_CLUSTER_ENABLED=False,
)
class TestQuotaRedis(SimpleTestCase):
    def setUp(self) -> None:
        quota_redis.clear_quota_redis_clients()
        self.addCleanup(quota_redis.clear_quota_redis_clients)

    @parameterized.expand(
        [
            (f"{mode}_{case}", cluster, host, trusted, accepted)
            for mode, cluster in [("standalone", False), ("cluster", True)]
            for case, host, trusted, accepted in [
                ("matching", "billing.example", True, True),
                ("wrong_hostname", "other.example", True, False),
                ("untrusted", "billing.example", False, False),
            ]
        ]
    )
    def test_tls_authenticates_the_connected_node(
        self, _name: str, cluster: bool, host: str, trusted: bool, accepted: bool
    ) -> None:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "billing.example")])
        now = datetime.now(UTC)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("billing.example")]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256())
        )
        with tempfile.TemporaryDirectory() as directory:
            cert_path = Path(directory) / "cert.pem"
            key_path = Path(directory) / "key.pem"
            cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            key_path.write_bytes(
                key.private_bytes(
                    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
                )
            )
            server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server_context.load_cert_chain(cert_path, key_path)
            url = "rediss://billing.example:6379?ssl_check_hostname=false&ssl_cert_reqs=none"
            if trusted:
                url += f"&ssl_ca_certs={quote(str(cert_path), safe='')}"
            with patch.object(NodesManager, "initialize"), patch("redis.cluster.CommandsParser"):
                client = quota_redis._build_client(url, cluster=cluster, maintenance=False)
                self.addCleanup(client.close)
                if isinstance(client, RedisCluster):
                    node = ClusterNode(host, 6379)
                    client.nodes_manager.create_redis_connections([node])
                    assert node.redis_connection is not None
                    pool = node.redis_connection.connection_pool
                else:
                    pool = client.connection_pool
                    pool.connection_kwargs["host"] = host
                connection = pool.make_connection()
                assert isinstance(connection, SSLConnection)
                wrap_socket: Callable[[socket.socket], ssl.SSLSocket] = connection._wrap_socket_with_ssl  # type: ignore[attr-defined] # redis-py's stubs omit the TLS hook.

            server_socket, client_socket = socket.socketpair()
            server_socket.settimeout(2)
            client_socket.settimeout(2)

            def serve() -> None:
                try:
                    with server_context.wrap_socket(server_socket, server_side=True) as stream:
                        stream.recv(1)
                except ssl.SSLError:
                    pass

            server = threading.Thread(target=serve)
            server.start()
            try:
                if accepted:
                    with wrap_socket(client_socket) as stream:
                        stream.sendall(b"x")
                else:
                    with self.assertRaises(ssl.SSLCertVerificationError):
                        with wrap_socket(client_socket) as stream:
                            stream.sendall(b"x")
            finally:
                client_socket.close()
                server_socket.close()
                server.join(timeout=3)
                self.assertFalse(server.is_alive())

    @override_settings(QUOTA_LIMITING_REDIS_URL=None)
    def test_unconfigured_secondary_does_not_construct_a_client(self) -> None:
        with patch("posthog.quota_redis._build_client") as cluster:
            self.assertIsNone(quota_redis.get_secondary_quota_redis_client())
        cluster.assert_not_called()

    @override_settings(QUOTA_LIMITING_REDIS_CLUSTER_ENABLED=True)
    def test_failed_cluster_discovery_can_recover_on_the_next_call(self) -> None:
        recovered = Mock(spec=Redis, connection_pool=Mock())
        with patch("posthog.quota_redis._build_client", side_effect=[RedisConnectionError("offline"), recovered]):
            with self.assertRaises(RedisConnectionError):
                quota_redis.get_secondary_quota_redis_client()
            self.assertIs(quota_redis.get_secondary_quota_redis_client(), recovered)
            self.assertIs(quota_redis.get_secondary_quota_redis_client(), recovered)

    @parameterized.expand(
        [
            ("standalone_write", False, False, 0.25, 64),
            ("standalone_maintenance", False, True, 5.0, 8),
            ("cluster_write", True, False, 0.25, 64),
            ("cluster_maintenance", True, True, 5.0, 8),
        ]
    )
    def test_connection_budget_cannot_be_overridden_by_url_options(
        self, _name: str, cluster: bool, maintenance: bool, timeout: float, maximum: int
    ) -> None:
        with (
            self.settings(
                QUOTA_LIMITING_REDIS_URL="redis://billing.invalid:6379/0?socket_timeout=90&socket_connect_timeout=90&max_connections=10000",
                QUOTA_LIMITING_REDIS_CLUSTER_ENABLED=cluster,
            ),
            patch.object(NodesManager, "initialize"),
            patch("redis.cluster.CommandsParser"),
        ):
            client = quota_redis.get_secondary_quota_redis_client(maintenance=maintenance)
        if isinstance(client, RedisCluster):
            node = ClusterNode("billing.invalid", 6379)
            client.nodes_manager.create_redis_connections([node])
            assert node.redis_connection is not None
            pool = node.redis_connection.connection_pool
        else:
            assert isinstance(client, Redis)
            pool = client.connection_pool
        self.assertEqual(pool.connection_kwargs["socket_timeout"], timeout)
        self.assertEqual(pool.connection_kwargs["socket_connect_timeout"], 0.5)
        self.assertEqual(pool.max_connections, maximum)

    def test_connection_failure_is_not_retried(self) -> None:
        client = quota_redis.get_secondary_quota_redis_client()
        assert client is not None
        with patch("redis.connection.Connection._connect", side_effect=OSError("offline")) as connect:
            with self.assertRaises(RedisConnectionError):
                client.ping()

        connect.assert_called_once()

    @parameterized.expand(
        [
            (f"{mode}_{scheme}", cluster, scheme)
            for mode, cluster in [("standalone", False), ("cluster", True)]
            for scheme in ["redis", "rediss"]
        ]
    )
    def test_blocked_hosts_are_rejected_before_dns(self, _name: str, cluster: bool, scheme: str) -> None:
        with (
            self.settings(
                QUOTA_LIMITING_REDIS_URL=f"{scheme}://blocked.example:6379/0",
                QUOTA_LIMITING_REDIS_CLUSTER_ENABLED=cluster,
            ),
            patch("posthog.security.oob_domains.oob_domains", return_value=frozenset({"blocked.example"})),
            patch("socket.getaddrinfo", side_effect=AssertionError("Unexpected DNS lookup")),
            self.assertRaisesRegex((RedisConnectionError, RedisClusterException), "Quota Redis host is not permitted"),
        ):
            client = quota_redis.get_secondary_quota_redis_client()
            assert client is not None
            client.ping()

    @override_settings(QUOTA_LIMITING_REDIS_CLUSTER_ENABLED=True)
    def test_blocked_discovered_node_is_rejected_before_dns(self) -> None:
        slots = [[0, 16383, [b"blocked.example", 6379, b"node"]]]
        with (
            patch.object(Redis, "execute_command", return_value=slots),
            patch("redis.cluster.CommandsParser.initialize"),
            patch("posthog.security.oob_domains.oob_domains", return_value=frozenset({"blocked.example"})),
            patch("socket.getaddrinfo", side_effect=AssertionError("Unexpected DNS lookup")) as resolve,
        ):
            with self.assertRaisesRegex(
                (RedisConnectionError, RedisClusterException), "Quota Redis host is not permitted"
            ):
                quota_redis.get_secondary_quota_redis_client()

        resolve.assert_not_called()
        assert not quota_redis._clients

    def test_concurrent_client_initialization_fails_without_building(self) -> None:
        busy = Mock()
        busy.acquire.return_value = False
        with (
            patch.object(quota_redis, "_initialization_locks", {}),
            patch("posthog.quota_redis.threading.Lock", return_value=busy),
            patch("posthog.quota_redis._build_client") as build,
        ):
            with self.assertRaisesMessage(RedisConnectionError, "initialization is busy"):
                quota_redis.get_secondary_quota_redis_client()
        busy.acquire.assert_called_once_with(timeout=0.25)
        busy.release.assert_not_called()
        build.assert_not_called()

    @parameterized.expand(
        [("standalone_clear", False, False), ("cluster_clear", True, False), ("cluster_replace", True, True)]
    )
    def test_cached_client_cleanup_disconnects_open_sockets(self, _name: str, cluster: bool, replace: bool) -> None:
        slots = [[0, 16383, [b"billing.invalid", 6379, b"node"]]]
        with (
            self.settings(
                QUOTA_LIMITING_REDIS_URL="redis://billing.invalid:6379/0", QUOTA_LIMITING_REDIS_CLUSTER_ENABLED=cluster
            ),
            patch.object(Redis, "execute_command", return_value=slots),
            patch("redis.cluster.CommandsParser.initialize"),
        ):
            client = quota_redis.get_secondary_quota_redis_client()
            assert client is not None
            if isinstance(client, RedisCluster):
                nodes = list(client.get_nodes())
                assert nodes[0].redis_connection is not None
                pool = nodes[0].redis_connection.connection_pool
            else:
                pool = client.connection_pool
            peer, connection_socket = socket.socketpair()
            self.addCleanup(peer.close)
            self.addCleanup(connection_socket.close)
            connection = pool.make_connection()
            connection._sock = connection_socket
            pool._available_connections.append(connection)
            if replace:
                assert isinstance(client, RedisCluster)
                client.nodes_manager.startup_nodes.clear()
                replacement = quota_redis.get_secondary_quota_redis_client()
                self.assertIsNot(replacement, client)
            else:
                quota_redis.clear_quota_redis_clients()
            peer.settimeout(0.1)
            self.assertEqual(peer.recv(1), b"")

    @override_settings(QUOTA_LIMITING_REDIS_CLUSTER_ENABLED=True)
    def test_established_cluster_recovers_after_losing_its_discovery_seed(self) -> None:
        node_redis = Mock()
        node_redis.execute_command.return_value = [[0, 16383, [b"billing.invalid", 6379, b"node"]]]
        with (
            patch.object(NodesManager, "create_redis_node", return_value=node_redis),
            patch("redis.cluster.CommandsParser.initialize"),
            patch("redis.cluster.CommandsParser.get_keys", return_value=["quota"]),
        ):
            client = quota_redis.get_secondary_quota_redis_client()
            assert isinstance(client, RedisCluster)
            with patch("redis.cluster.get_connection", side_effect=RedisConnectionError("Too many connections")):
                with self.assertRaises((RedisError, RedisClusterException)):
                    client.execute_command("ZSCORE", "quota", "team")

            recovered = quota_redis.get_secondary_quota_redis_client()
            assert isinstance(recovered, RedisCluster)
            self.assertIsNot(recovered, client)
            self.assertIsNone(client.nodes_manager.default_node)
            node_redis.parse_response.return_value = 123
            with patch("redis.cluster.get_connection", return_value=Mock()):
                self.assertEqual(recovered.execute_command("ZSCORE", "quota", "team"), 123)

    @override_settings(QUOTA_LIMITING_REDIS_CLUSTER_ENABLED=True)
    def test_forked_child_can_collect_inherited_cluster_with_locked_connections(self) -> None:
        # Finalize earlier tests' garbage here: its finalizers can block in a forked child.
        gc.collect()
        slots = [[0, 16383, [b"billing.invalid", 6379, b"node"]]]
        with (
            patch.object(Redis, "execute_command", return_value=slots),
            patch("redis.cluster.CommandsParser.initialize"),
        ):
            client = quota_redis.get_secondary_quota_redis_client()
        assert isinstance(client, RedisCluster)
        locks = [client._lock]  # type: ignore[attr-defined] # The cluster lock is absent from redis-py's stubs.
        for node in client.get_nodes():
            assert node.redis_connection is not None
            pool = node.redis_connection.connection_pool
            locks.extend([pool._lock, pool._fork_lock])
        for lock in locks:
            lock.acquire()
        del client, node, pool
        read_fd, write_fd = os.pipe()
        child_pid = os.fork()
        if child_pid == 0:
            os.close(read_fd)
            gc.collect()
            os.write(write_fd, b"ok")
            os._exit(0)
        os.close(write_fd)
        try:
            readable, _, _ = select.select([read_fd], [], [], 30)
            self.assertTrue(readable, "Inherited Redis locks blocked child garbage collection")
            self.assertEqual(os.read(read_fd, 2), b"ok")
        finally:
            for lock in locks:
                lock.release()
            os.close(read_fd)
            if os.waitpid(child_pid, os.WNOHANG)[0] == 0:
                os.kill(child_pid, signal.SIGKILL)
                os.waitpid(child_pid, 0)
