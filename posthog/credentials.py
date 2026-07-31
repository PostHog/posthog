from dataclasses import dataclass, field
from typing import NewType

# Distinct static types for the two halves of an AWS key pair. They are plain `str` at runtime.
# The point is that a type checker rejects passing a secret where a key id is expected.
AWSAccessKeyId = NewType("AWSAccessKeyId", str)
AWSSecretAccessKey = NewType("AWSSecretAccessKey", str)


@dataclass(frozen=True)
class AWSKeyPair:
    """An AWS access key and its secret, kept together.

    Pass this rather than the two halves: callers taking a single argument have no order to get
    wrong, and code holding one cannot end up with the key present and the secret missing. Where
    credentials are optional (keyless IAM auth), use `AWSKeyPair | None` so that "no credentials"
    stays distinct from "half a pair".
    """

    access_key_id: AWSAccessKeyId
    secret_access_key: AWSSecretAccessKey = field(repr=False)

    @classmethod
    def unsafe_from_strings(cls, access_key_id: str, secret_access_key: str) -> "AWSKeyPair":
        """Brand two raw strings as a key pair.

        Unsafe because nothing checks the arguments are the right way round: this is the only
        place where getting it wrong is possible. Call it where a credential enters the process
        (settings, integration config, a secrets manager), and pass the pair around from there.
        """
        return cls(
            access_key_id=AWSAccessKeyId(access_key_id),
            secret_access_key=AWSSecretAccessKey(secret_access_key),
        )
