from typing import NewType, overload

# Distinct static types for the two halves of an AWS key pair. They are plain `str` at runtime;
# the point is that a type checker rejects passing a secret where a key id is expected, so a
# transposed pair fails the type check instead of silently authenticating as the wrong thing.
AWSAccessKeyId = NewType("AWSAccessKeyId", str)
AWSSecretAccessKey = NewType("AWSSecretAccessKey", str)


@overload
def unsafe_cast_aws_credentials(
    access_key_id: str, secret_access_key: str
) -> tuple[AWSAccessKeyId, AWSSecretAccessKey]: ...


@overload
def unsafe_cast_aws_credentials(
    access_key_id: str | None, secret_access_key: str | None
) -> tuple[AWSAccessKeyId | None, AWSSecretAccessKey | None]: ...


def unsafe_cast_aws_credentials(
    access_key_id: str | None, secret_access_key: str | None
) -> tuple[AWSAccessKeyId | None, AWSSecretAccessKey | None]:
    """Turn two raw strings into a branded AWS key pair.

    Unsafe because nothing checks that the arguments are the right way round: this is the one
    place where getting it wrong is possible. Call it only where a credential enters the process
    (settings, integration config, a secrets manager). Everything downstream takes the branded
    types, so from here on the type checker enforces which half is which.
    """
    return (
        None if access_key_id is None else AWSAccessKeyId(access_key_id),
        None if secret_access_key is None else AWSSecretAccessKey(secret_access_key),
    )
