import typing
import dataclasses
from io import StringIO
from typing import IO, Literal

from cryptography.hazmat.primitives import serialization as crypto_serialization
from cryptography.hazmat.primitives.asymmetric import dsa, ec, ed25519, rsa
from paramiko import DSSKey, ECDSAKey, Ed25519Key, PKey, RSAKey
from sshtunnel import SSHTunnelForwarder

from posthog.temporal.data_imports.sources.common import config


# Taken from https://stackoverflow.com/questions/60660919/paramiko-ssh-client-is-unable-to-unpack-ed25519-key
def from_private_key(file_obj: IO[str], passphrase: str | None = None) -> PKey:
    private_key: PKey | None = None
    file_bytes = bytes(file_obj.read(), "utf-8")
    password = bytes(StringIO(passphrase).read(), "utf-8")
    try:
        key = crypto_serialization.load_ssh_private_key(
            file_bytes,
            password=password,
        )
        file_obj.seek(0)
    except ValueError:
        key = crypto_serialization.load_pem_private_key(  # type: ignore
            file_bytes,
            password=password if passphrase is not None else None,
        )
        if passphrase:
            encryption_algorithm = crypto_serialization.BestAvailableEncryption(password)
        else:
            encryption_algorithm = crypto_serialization.NoEncryption()
        file_obj = StringIO(
            key.private_bytes(
                crypto_serialization.Encoding.PEM,
                crypto_serialization.PrivateFormat.OpenSSH,
                encryption_algorithm,
            ).decode("utf-8")
        )
    if isinstance(key, rsa.RSAPrivateKey):
        private_key = RSAKey.from_private_key(file_obj, passphrase)
    elif isinstance(key, ed25519.Ed25519PrivateKey):
        private_key = Ed25519Key.from_private_key(file_obj, passphrase)
    elif isinstance(key, ec.EllipticCurvePrivateKey):
        private_key = ECDSAKey.from_private_key(file_obj, passphrase)
    elif isinstance(key, dsa.DSAPrivateKey):
        private_key = DSSKey.from_private_key(file_obj, passphrase)
    else:
        raise TypeError

    return private_key


@config.config
class SSHTunnelAuthConfig(config.Config):
    """Configuration for SSH tunnel authentication."""

    type: Literal["password", "keypair"] | None = config.value(alias="selection")
    password: str | None = None
    passphrase: str | None = None
    private_key: str | None = None
    username: str | None = None


@config.config
class SSHTunnelConfig(config.Config):
    host: str | None
    auth: SSHTunnelAuthConfig = config.value(alias="auth_type")
    port: int | None = config.value(converter=config.str_to_optional_int)
    enabled: bool = config.value(converter=config.str_to_bool, default=False)


@dataclasses.dataclass
class SSHTunnel:
    enabled: bool

    host: str
    port: int | str
    auth_type: Literal["password", "keypair"]
    username: str | None
    password: str | None
    private_key: str | None
    passphrase: str | None

    @classmethod
    def from_config(cls: type[typing.Self], config: SSHTunnelConfig) -> typing.Self:
        # We should not be calling this if SSH tunneling is not enabled.
        # Currently, we don't: The function is always guarded by an if check.
        # However, this is not reliable: Anybody can forget the if and introduce
        # a bug.
        # TODO: Refactor this so that we don't need these assertions nor can we
        # fail if somebody forgets an if check.
        assert config.host
        assert config.port
        assert config.auth.type

        return cls(
            enabled=config.enabled,
            host=config.host,
            port=config.port,
            auth_type=config.auth.type,
            username=config.auth.username,
            password=config.auth.password,
            private_key=config.auth.private_key,
            passphrase=config.auth.passphrase,
        )

    def parse_private_key(self) -> PKey:
        if self.passphrase is None:
            passphrase = None
        elif len(self.passphrase) == 0:
            passphrase = None
        else:
            passphrase = self.passphrase

        return from_private_key(StringIO(self.private_key), passphrase)

    def is_auth_valid(self) -> tuple[bool, str]:
        if self.auth_type != "password" and self.auth_type != "keypair":
            return False, "Authentication type not recognised"  # type: ignore

        if self.auth_type == "password":
            valid_username = self.username is not None and len(self.username) > 0
            valid_password = self.password is not None and len(self.password) > 0

            return valid_username and valid_password, "Username and password required"

        if self.auth_type == "keypair":
            valid_private_key = self.private_key is not None and len(self.private_key) > 0
            if not valid_private_key:
                return False, "Private key is required"

            try:
                self.parse_private_key()
            except:
                # TODO: More helpful error messages
                return False, "Private key could not be parsed"

            return True, ""

        return False, ""  # type: ignore

    def has_valid_port(self) -> tuple[bool, str]:
        port = int(self.port)
        if port == 80 or port == 443:
            return False, f"Port {port} is not allowed"

        return True, ""

    def get_tunnel(self, remote_host: str, remote_port: int) -> SSHTunnelForwarder:
        if not self.is_auth_valid()[0]:
            raise Exception("SSHTunnel auth is not valid")

        if not self.has_valid_port()[0]:
            raise Exception("SSHTunnel port is not valid")

        if self.auth_type == "password":
            return SSHTunnelForwarder(
                (self.host, int(self.port)),
                ssh_username=self.username,
                ssh_password=self.password,
                remote_bind_address=(remote_host, remote_port),
            )
        else:
            return SSHTunnelForwarder(
                (self.host, int(self.port)),
                ssh_username=self.username,
                ssh_pkey=self.parse_private_key(),
                ssh_private_key_password=self.passphrase,
                remote_bind_address=(remote_host, remote_port),
            )
