"""Token-checked lock operations, shared by every lock that stores its owner's token as the value.

After a TTL expires another caller may hold the key, so renewing or releasing has to compare the
token and act in one step: a plain get-then-expire or get-then-delete could extend or drop the
new owner's lock. Each script is called with the client first, e.g.
``delete_if_owner(client, key=lock_key, token=token)``, and works on sync and async clients alike.
"""

from redis_lua_py import Key, redis, script


@script
def delete_if_owner(key: Key, token: str) -> int:
    """Delete `key` only while it still holds `token`. Returns 1 when deleted, else 0."""
    if redis.get(key) == token:
        return redis.delete(key)
    return 0


@script
def expire_if_owner(key: Key, token: str, seconds: int) -> int:
    """Reset the TTL of `key` only while it still holds `token`. Returns 1 when extended, else 0."""
    if redis.get(key) == token:
        return redis.expire(key, seconds)
    return 0


@script
def pexpire_if_owner(key: Key, token: str, milliseconds: int) -> int:
    """Like `expire_if_owner`, with the TTL in milliseconds."""
    if redis.get(key) == token:
        return redis.pexpire(key, milliseconds)
    return 0
