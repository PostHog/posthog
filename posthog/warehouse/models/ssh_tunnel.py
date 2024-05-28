import dataclasses
from io import StringIO
from typing import Literal
from sshtunnel import SSHTunnelForwarder
from paramiko import RSAKey


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

    def parse_private_key(self) -> RSAKey:
        if self.passphrase is None:
            passphrase = None
        elif len(self.passphrase) == 0:
            passphrase = None
        else:
            passphrase = self.passphrase

        return RSAKey.from_private_key(StringIO(self.private_key), passphrase)

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
                ssh_pkey=self.parse_private_key(),
                ssh_private_key_password=self.passphrase,
                remote_bind_address=(remote_host, remote_port),
            )
