import pytest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from products.warehouse_sources.backend.facade.models import SSHTunnel


def _keypair_tunnel(private_key: str | None, passphrase: str | None) -> SSHTunnel:
    return SSHTunnel(
        enabled=True,
        host="host.com",
        port=5432,
        auth_type="keypair",
        username=None,
        password=None,
        private_key=private_key,
        passphrase=passphrase,
    )


@pytest.mark.parametrize("port,expected", [(5432, True), (80, False), (443, False)])
def test_valid_port(port, expected):
    ssh_tunnel = SSHTunnel(
        enabled=True,
        host="host.com",
        port=port,
        auth_type="password",
        username="user1",
        password="password",
        private_key=None,
        passphrase=None,
    )

    res, error = ssh_tunnel.has_valid_port()

    assert res is expected


@pytest.mark.parametrize(
    "username,password,expected",
    [
        ("User1", "password", True),
        ("", "password", False),
        ("user", "", False),
        ("", "", False),
        ("User", None, False),
        (None, "password", False),
    ],
)
def test_is_auth_valid_password(username, password, expected):
    ssh_tunnel = SSHTunnel(
        enabled=True,
        host="host.com",
        port=5432,
        auth_type="password",
        username=username,
        password=password,
        private_key=None,
        passphrase=None,
    )

    res, error = ssh_tunnel.is_auth_valid()

    assert res is expected


@pytest.mark.parametrize(
    "private_key,passphrase,expected",
    [
        ("Blah", "password", False),
        ("", "password", False),
        (None, "password", False),
        ("Blah", "", False),
        ("Blah", None, False),
    ],
)
def test_is_auth_valid_key_pair(private_key, passphrase, expected):
    ssh_tunnel = SSHTunnel(
        enabled=True,
        host="host.com",
        port=5432,
        auth_type="keypair",
        username=None,
        password=None,
        private_key=private_key,
        passphrase=passphrase,
    )

    res, error = ssh_tunnel.is_auth_valid()

    assert res is expected


def test_is_auth_valid_unparseable_key_suggests_format():
    res, error = _keypair_tunnel(private_key="not a private key", passphrase=None).is_auth_valid()

    assert res is False
    assert "OpenSSH or PEM" in error


def test_is_auth_valid_wrong_passphrase_suggests_passphrase():
    key = ed25519.Ed25519PrivateKey.generate()
    encrypted = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.BestAvailableEncryption(b"correct-passphrase"),
    ).decode()

    res, error = _keypair_tunnel(private_key=encrypted, passphrase="wrong-passphrase").is_auth_valid()

    assert res is False
    assert "passphrase" in error.lower()


def test_get_tunnel_invalid_auth():
    ssh_tunnel = SSHTunnel(
        enabled=True,
        host="host.com",
        port=5432,
        auth_type="password",
        username="",
        password="",
        private_key=None,
        passphrase=None,
    )

    with pytest.raises(Exception) as e:
        ssh_tunnel.get_tunnel("host.com", 1337)
        assert "auth" in str(e.value)


def test_get_tunnel_invalid_port():
    ssh_tunnel = SSHTunnel(
        enabled=True,
        host="host.com",
        port=80,
        auth_type="password",
        username="user",
        password="password",
        private_key=None,
        passphrase=None,
    )

    with pytest.raises(Exception) as e:
        ssh_tunnel.get_tunnel("host.com", 1337)
        assert "port" in str(e.value)
